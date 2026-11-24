import io
import zipfile
from xml.sax.saxutils import escape


COLORS = {
    "velame": "ff0000ff",
    "queda": "ffffffff",
    "arrasto": "ffff0000",
    "dispersao": "ff00ffff",
    "margem": "ff000000",
    "pouso": "ff00ff00",
    "minuto_fora": "ffff00ff",
}


def _style_definitions():
    line_styles = "\n".join(
        '<Style id="linha{0}"><LineStyle><color>{1}</color><width>4</width></LineStyle></Style>'.format(
            kind.title(), color
        )
        for kind, color in COLORS.items()
    )
    icon_styles = (
        '<Style id="targetIcon"><IconStyle><Icon><href>'
        'http://maps.google.com/mapfiles/kml/paddle/red-stars.png'
        '</href></Icon></IconStyle></Style>'
        '<Style id="pointIcon"><IconStyle><Icon><href>'
        'http://maps.google.com/mapfiles/kml/paddle/ylw-blank.png'
        '</href></Icon></IconStyle></Style>'
    )
    return line_styles, icon_styles


def _placemark_xml(placemark):
    name = escape(placemark["name"])
    description = (
        "<description>{}</description>".format(escape(str(placemark["description"])))
        if placemark.get("description")
        else ""
    )
    if placemark["type"] == "point":
        lat, lon = placemark["coordinates"]
        style = "targetIcon" if placemark["name"].upper() == "ALVO" else "pointIcon"
        return (
            '<Placemark><name>{0}</name>{1}<styleUrl>#{2}</styleUrl><Point>'
            '<coordinates>{3},{4},0</coordinates></Point></Placemark>'.format(
                name, description, style, lon, lat
            )
        )
    coordinates = " ".join(
        "{0},{1},0".format(lon, lat)
        for lat, lon in placemark["coordinates"]
    )
    style = "linha" + placemark["style"].title()
    return (
        '<Placemark><name>{0}</name>{1}<styleUrl>#{2}</styleUrl><LineString>'
        '<extrude>1</extrude><tessellate>1</tessellate><coordinates>{3}</coordinates>'
        '</LineString></Placemark>'.format(name, description, style, coordinates)
    )


def build_kml(folder_name, placemarks):
    line_styles, icon_styles = _style_definitions()
    elements = "".join(_placemark_xml(placemark) for placemark in placemarks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{0}</name>{1}{2}'
        '<Folder><name>{0}</name>{3}</Folder></Document></kml>'
    ).format(escape(folder_name), line_styles, icon_styles, elements)


def build_kml_folders(document_name, folders):
    line_styles, icon_styles = _style_definitions()
    folder_xml = []
    for folder in folders:
        elements = "".join(_placemark_xml(item) for item in folder["placemarks"])
        folder_xml.append(
            "<Folder><name>{}</name>{}</Folder>".format(
                escape(folder["name"]),
                elements,
            )
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{0}</name>{1}{2}{3}'
        '</Document></kml>'
    ).format(escape(document_name), line_styles, icon_styles, "".join(folder_xml))


def export_kmz(folder_name, placemarks, kml_name="doc.kml"):
    kml = build_kml(folder_name, placemarks)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(kml_name, kml)
    return buffer.getvalue()


def export_kmz_folders(document_name, folders, kml_name="doc.kml"):
    kml = build_kml_folders(document_name, folders)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(kml_name, kml)
    return buffer.getvalue()
