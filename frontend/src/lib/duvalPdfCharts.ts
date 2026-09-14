import { createElement, type ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { api } from '../api'
import DualPentagon from '../charts/DualPentagon'
import DualTriangles from '../charts/DuvalTriangle'
import type {
  DgaStatusReport,
  DuvalAnalysis,
  PentagonGeometry,
  TriangleGeometry,
} from '../types'
import type { DuvalPdfExtras, PdfChart } from './dgaStatusPdf'

/**
 * Duval charts as images for the DGA status PDF.
 *
 * jsPDF cannot draw SVG, so the charts are rendered with the very components the
 * Duval screens use, rasterised to PNG and placed as images. Reusing the
 * components rather than redrawing the diagrams in jsPDF means the printed zones
 * can never drift from the ones an engineer sees on screen.
 */

export interface DuvalPdfOptions {
  triangles: boolean
  pentagons: boolean
}

/** The same pair Trend Analysis shows as "Duval Dual Triangles". */
export const DUAL_TRIANGLE_IDS = ['1', '5']

// Wide enough to stay sharp at half an A4 page width when printed.
const RASTER_WIDTH = 1000

/**
 * The chart <svg>s a component renders, detached and ready to serialise.
 *
 * Only `role="img"` - the panels also carry lucide icons (the "Provisional"
 * chip), which are SVGs too and would otherwise print as a third "chart".
 */
function svgsOf(element: ReactElement): SVGSVGElement[] {
  const html = renderToStaticMarkup(element)
  const parsed = new DOMParser().parseFromString(html, 'text/html')
  return Array.from(parsed.querySelectorAll<SVGSVGElement>('svg[role="img"]'))
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('Could not render a Duval chart for the PDF.'))
    img.src = src
  })
}

async function rasterise(svg: SVGSVGElement): Promise<PdfChart> {
  const [x0, y0, w0, h0] = (svg.getAttribute('viewBox') ?? '').split(/\s+/).map(Number)
  if (!w0 || !h0) throw new Error('Duval chart has no view box.')
  // Vertex labels such as "% C2H4" sit right on the edge of the view box and
  // are clipped once rasterised in a wider font, so the canvas gets a margin.
  const mx = w0 * 0.06
  const my = h0 * 0.03
  const vw = w0 + mx * 2
  const vh = h0 + my * 2
  svg.setAttribute('viewBox', `${x0 - mx} ${y0 - my} ${vw} ${vh}`)
  const width = RASTER_WIDTH
  const height = Math.round((width * vh) / vw)

  // The on-screen sizing comes from CSS classes that do not exist inside an
  // image, so the pixel size is stated on the element itself.
  svg.removeAttribute('class')
  svg.removeAttribute('style')
  svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  svg.setAttribute('width', String(width))
  svg.setAttribute('height', String(height))
  svg.setAttribute('font-family', 'Segoe UI, Helvetica, Arial, sans-serif')

  const xml = new XMLSerializer().serializeToString(svg)
  const img = await loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`)

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('This browser cannot draw the Duval charts.')
  // PNG has no background of its own; white keeps the zones true on paper.
  ctx.fillStyle = '#FFFFFF'
  ctx.fillRect(0, 0, width, height)
  ctx.drawImage(img, 0, 0, width, height)
  return { dataUrl: canvas.toDataURL('image/png'), aspect: height / width }
}

/**
 * Gases to diagnose.
 *
 * A stored asset goes through the asset path, so the PDF shows exactly what the
 * Duval screens show for that unit. Hand-entered data has no asset to look up,
 * so the newest reading of each gas from the status evidence is sent instead.
 */
function analyseBody(report: DgaStatusReport): Record<string, unknown> {
  if (report.source !== 'manual') return { asset: report.asset }
  const gases: Record<string, number> = {}
  for (const g of report.status.gases) gases[g.gas] = g.latest ?? 0
  return { gases, sampleDate: report.status.latestSample }
}

export async function buildDuvalExtras(
  report: DgaStatusReport,
  options: DuvalPdfOptions,
): Promise<DuvalPdfExtras | undefined> {
  if (!options.triangles && !options.pentagons) return undefined

  const [geometry, analysis] = await Promise.all([
    api.get<{ pentagon: PentagonGeometry; triangles: Record<string, TriangleGeometry> }>(
      '/duval/geometry',
    ),
    api.post<DuvalAnalysis>('/duval/analyse', analyseBody(report)),
  ])

  const extras: DuvalPdfExtras = {
    sampleDate: analysis.sampleDate
      ? String(analysis.sampleDate).slice(0, 10)
      : report.status.latestSample,
    gases: analysis.gases,
  }

  if (options.triangles) {
    const ids = DUAL_TRIANGLE_IDS.filter((id) => geometry.triangles[id])
    const svgs = svgsOf(
      createElement(DualTriangles, {
        geometries: geometry.triangles,
        results: analysis.triangles,
        ids,
      }),
    )
    extras.triangles = {
      charts: await Promise.all(svgs.map(rasterise)),
      titles: ids.map((id) => geometry.triangles[id].title),
      results: ids.map((id) => analysis.triangles[id]).filter(Boolean),
    }
  }

  if (options.pentagons) {
    const svgs = svgsOf(
      createElement(DualPentagon, { geometry: geometry.pentagon, result: analysis.pentagon }),
    )
    extras.pentagons = {
      charts: await Promise.all(svgs.map(rasterise)),
      titles: [geometry.pentagon.pentagon1.title, geometry.pentagon.pentagon2.title],
      result: analysis.pentagon,
    }
  }

  return extras
}
