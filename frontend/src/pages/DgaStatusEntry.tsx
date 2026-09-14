import { Keyboard } from 'lucide-react'
import DgaManualAssessment from '../components/DgaManualAssessment'
import { SectionHeader } from '../components/ui'

/**
 * DGA Status Entry — the status classifier over values typed in by hand.
 *
 * Its own section rather than a mode of the DGA Status screen, because it
 * answers a different question with a different input. That screen asks "what
 * status is this transformer in", starting from an asset number and reading the
 * database. This one asks "what does the standard make of these numbers",
 * starting from a test certificate — for a unit whose laboratory results have
 * not been loaded, a sample taken today, or a check of the port itself against
 * the guide's own test vector.
 *
 * Neither the entered values nor the result are written to the database. The
 * report it produces is the same document a stored asset gets, and is exported
 * the same way.
 */
export default function DgaStatusEntry() {
  return (
    <div>
      <div className="print-hide">
        <SectionHeader
          accent="#195B96"
          icon={Keyboard}
          title="DGA Status Entry"
          subtitle="Classify dissolved-gas results you type in — IEEE C57.104-2019,
                    with the same evidence table and report as a stored asset"
        />
      </div>
      <DgaManualAssessment />
    </div>
  )
}
