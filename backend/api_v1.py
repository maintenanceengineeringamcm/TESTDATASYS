"""Public, versioned API documented with OpenAPI and served through Swagger UI.

Two read-only endpoints for integration and demonstration:

* ``GET /api/v1/asset-hierarchy`` - the substation > discipline > voltage > bay >
  equipment tree, nested to a chosen depth from the roots or from any node.
* ``GET /api/v1/tests`` - the tests held in the test database, with fleet-wide
  record counts, or one asset's records per test when ``asset`` is given.

The interactive documentation is at ``/apidocs/`` and the raw specification at
``/apispec_v1.json``. Only ``/api/v1/`` routes appear there; the internal routes
the UI calls are unversioned and free to change.
"""
from __future__ import annotations

from flasgger import Swagger, swag_from
from flask import Blueprint, Flask, jsonify, request

from core import hierarchy, history
from core.readers import OPEN_FROM, OPEN_TO

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# The full tree is ~24k nodes; past this a response stops being demo-sized.
MAX_DEPTH = 10

TEMPLATE = {
    "swagger": "2.0",
    "info": {
        "title": "Asset Health Index - Public API",
        "version": "1.0.0",
        "description": (
            "Read-only access to the CEB transmission **asset hierarchy** and the "
            "**test database test list**.\n\n"
            "Open an endpoint, press **Try it out**, then **Execute**."
        ),
    },
    "tags": [
        {"name": "Asset hierarchy",
         "description": "Substation > discipline > voltage > bay > equipment > unit"},
        {"name": "Tests", "description": "Tests held in the test database"},
    ],
    "definitions": {
        "HierarchyNode": {
            "type": "object",
            "properties": {
                "assetNo": {"type": "string", "example": "G008/PE/1"},
                "parentId": {"type": "string", "x-nullable": True, "example": "G008/PE"},
                "code": {"type": "string", "example": "1"},
                "label": {"type": "string", "example": "132kV Primary Equipment"},
                "named": {"type": "boolean",
                          "description": "True when the label is the CMMS short "
                                         "description, false when derived from the code"},
                "kind": {"type": "string",
                         "enum": ["site", "unassigned", "discipline", "voltage", "bay",
                                  "equipment", "oltc", "unit"]},
                "depth": {"type": "integer", "example": 3},
                "path": {"type": "string", "example": "Biyagama GS > Primary Equipment > 132kV Primary Equipment"},
                "assetCount": {"type": "integer",
                               "description": "In-service assets in this subtree"},
                "categories": {"type": "array", "items": {"type": "string"},
                               "example": ["CB", "CTVT", "TR"]},
                "isAsset": {"type": "boolean"},
                "childCount": {"type": "integer",
                               "description": "Direct children, including any not "
                                            "expanded because of the depth limit"},
                "assetType": {"type": "string", "description": "Asset nodes only"},
                "category": {"type": "string", "description": "Asset nodes only"},
                "status": {"type": "string", "x-nullable": True,
                           "description": "Asset nodes only"},
                "children": {"type": "array",
                             "items": {"$ref": "#/definitions/HierarchyNode"}},
            },
        },
        "HierarchyResponse": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "x-nullable": True},
                "depth": {"type": "integer"},
                "returnedNodes": {"type": "integer"},
                "ancestors": {"type": "array",
                              "description": "Breadcrumb from the top down to root "
                                             "(empty when root is not given)",
                              "items": {"$ref": "#/definitions/HierarchyNode"}},
                "stats": {"type": "object",
                          "description": "Whole-tree totals: source, nodes, assets, "
                                         "roots, named, maxDepth, status"},
                "items": {"type": "array",
                          "items": {"$ref": "#/definitions/HierarchyNode"}},
            },
        },
        "Test": {
            "type": "object",
            "properties": {
                "testId": {"type": "string", "example": "TEST001"},
                "name": {"type": "string", "example": "DGA"},
                "kind": {"type": "string", "enum": ["table", "omicron"]},
                "table": {"type": "string", "example": "CEB_DGA_DATA"},
                "dateColumn": {"type": "string", "example": "DateSampled"},
                "available": {"type": "boolean",
                              "description": "At least one record exists"},
                "records": {"type": "integer", "example": 3288},
                "assets": {"type": "integer",
                           "description": "Distinct assets tested (fleet-wide list only)"},
                "firstTested": {"type": "string", "x-nullable": True,
                                "description": "Fleet-wide list only"},
                "lastTested": {"type": "string", "x-nullable": True},
                "message": {"type": "string",
                            "description": "Present when the source could not be read"},
            },
        },
        "TestsResponse": {
            "type": "object",
            "properties": {
                "asset": {"type": "string", "x-nullable": True},
                "kind": {"type": "string", "x-nullable": True},
                "dateFrom": {"type": "string", "x-nullable": True},
                "dateTo": {"type": "string", "x-nullable": True},
                "total": {"type": "integer"},
                "items": {"type": "array", "items": {"$ref": "#/definitions/Test"}},
            },
        },
        "Error": {
            "type": "object",
            "properties": {"error": {"type": "string"}, "message": {"type": "string"}},
        },
    },
}

CONFIG = {
    "headers": [],
    "specs": [{
        "endpoint": "apispec_v1",
        "route": "/apispec_v1.json",
        "rule_filter": lambda rule: rule.rule.startswith("/api/v1/"),
        "model_filter": lambda tag: True,
    }],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/",
}


def _bad_request(message: str):
    return jsonify({"error": "bad_request", "message": message}), 400


@bp.get("/asset-hierarchy")
@swag_from({
    "tags": ["Asset hierarchy"],
    "summary": "Asset hierarchy tree",
    "description": (
        "Returns the hierarchy nested `depth` levels deep.\n\n"
        "* No `root`: starts at the substations.\n"
        "* With `root`: starts at that node, and `ancestors` gives its breadcrumb.\n\n"
        "Nodes beyond the depth limit come back with an empty `children` list "
        "but a non-zero `childCount`. Pass one of those `assetNo` values as "
        "`root` to drill in."
    ),
    "parameters": [
        {"name": "root", "in": "query", "type": "string", "required": False,
         "description": "Asset number to start from, e.g. `G008` or `G008/PE/2`"},
        {"name": "depth", "in": "query", "type": "integer", "required": False,
         "default": 1, "minimum": 0, "maximum": MAX_DEPTH,
         "description": "Levels of children to include (0 = the start node only)"},
    ],
    "responses": {
        "200": {"description": "The tree", "schema": {"$ref": "#/definitions/HierarchyResponse"}},
        "400": {"description": "Invalid depth", "schema": {"$ref": "#/definitions/Error"}},
        "404": {"description": "Unknown root", "schema": {"$ref": "#/definitions/Error"}},
    },
})
def asset_hierarchy():
    root = (request.args.get("root") or "").strip().strip("/") or None
    try:
        depth = int(request.args.get("depth", 1))
    except ValueError:
        return _bad_request("depth must be an integer.")
    if not 0 <= depth <= MAX_DEPTH:
        return _bad_request(f"depth must be between 0 and {MAX_DEPTH}.")

    items = hierarchy.subtree(root, depth)
    if items is None:
        return jsonify({"error": "not_found",
                        "message": f"Unknown hierarchy node '{root}'."}), 404

    def count(nodes):
        return sum(1 + count(n["children"]) for n in nodes)

    return jsonify({
        "root": root,
        "depth": depth,
        "returnedNodes": count(items),
        "ancestors": hierarchy.ancestors(root)[:-1] if root else [],
        "stats": hierarchy.stats(),
        "items": items,
    })


@bp.get("/tests")
@swag_from({
    "tags": ["Tests"],
    "summary": "Test database test list",
    "description": (
        "Lists every test the system reads from the test database: the oil and "
        "electrical test tables and the Omicron test executions.\n\n"
        "* No `asset`: fleet-wide totals per test - records, distinct assets, "
        "first and last test date. Cached for 10 minutes. Placeholder and "
        "future dates (e.g. `1753-01-01`) count as records but are ignored for "
        "the first/last dates.\n"
        "* With `asset`: that asset's record count and last test date per test, "
        "optionally within `from`/`to`."
    ),
    "parameters": [
        {"name": "asset", "in": "query", "type": "string", "required": False,
         "description": "Asset number, e.g. `G008/PE/2/05/IBT02_B/01`"},
        {"name": "kind", "in": "query", "type": "string", "required": False,
         "enum": ["table", "omicron"], "description": "Only tests of this kind"},
        {"name": "available", "in": "query", "type": "boolean", "required": False,
         "description": "true = only tests with records, false = only tests without"},
        {"name": "from", "in": "query", "type": "string", "format": "date",
         "required": False, "description": "Start date (asset view only), e.g. `2020-01-01`"},
        {"name": "to", "in": "query", "type": "string", "format": "date",
         "required": False, "description": "End date (asset view only)"},
    ],
    "responses": {
        "200": {"description": "The test list", "schema": {"$ref": "#/definitions/TestsResponse"}},
        "400": {"description": "Invalid filter", "schema": {"$ref": "#/definitions/Error"}},
    },
})
def tests():
    asset = (request.args.get("asset") or "").strip() or None
    kind = request.args.get("kind") or None
    if kind not in (None, "table", "omicron"):
        return _bad_request("kind must be 'table' or 'omicron'.")
    available = (request.args.get("available") or "").lower() or None
    if available not in (None, "true", "false"):
        return _bad_request("available must be true or false.")

    if asset:
        date_from = request.args.get("from") or OPEN_FROM
        date_to = request.args.get("to") or OPEN_TO
        items = history.asset_summary(asset, date_from, date_to)
    else:
        date_from = date_to = None
        items = history.fleet_summary()

    if kind:
        items = [t for t in items if t["kind"] == kind]
    if available:
        items = [t for t in items if t["available"] == (available == "true")]

    return jsonify({"asset": asset, "kind": kind,
                    "dateFrom": date_from, "dateTo": date_to,
                    "total": len(items), "items": items})


def init_app(app: Flask) -> None:
    app.register_blueprint(bp)
    Swagger(app, template=TEMPLATE, config=CONFIG)
