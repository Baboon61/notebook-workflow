#!/usr/bin/env python3
"""Build the dependency-free local extension as a VSIX using the standard ZIP layout."""

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile


BUNDLE = Path(__file__).resolve().parents[1]


def package(destination: Path) -> Path:
    extension = BUNDLE / "vscode"
    metadata = json.loads((extension / "package.json").read_text())
    filename = destination / f"{metadata['name']}-{metadata['version']}.vsix"
    destination.mkdir(parents=True, exist_ok=True)
    manifest = f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
 <Metadata>
  <Identity Language="en-US" Id="{metadata['name']}" Version="{metadata['version']}" Publisher="{metadata['publisher']}"/>
  <DisplayName>{escape(metadata['displayName'])}</DisplayName>
  <Description xml:space="preserve">{escape(metadata['description'])}</Description>
  <License>extension/LICENSE</License>
  <Categories>Notebooks</Categories>
  <Properties>
   <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{escape(metadata['engines']['vscode'])}"/>
   <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="ui"/>
  </Properties>
 </Metadata>
 <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
 <Dependencies/>
 <Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/></Assets>
</PackageManifest>
'''
    types = '''<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="json" ContentType="application/json"/>
 <Default Extension="js" ContentType="application/javascript"/>
 <Default Extension="md" ContentType="text/markdown"/>
 <Default Extension="vsixmanifest" ContentType="text/xml"/>
 <Override PartName="/extension/LICENSE" ContentType="text/plain"/>
</Types>
'''
    with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("extension.vsixmanifest", manifest)
        archive.writestr("[Content_Types].xml", types)
        for name in ("package.json", "extension.js", "bridge.js", "notebooks.js", "README.md"):
            archive.write(extension / name, "extension/" + name)
        archive.write(BUNDLE / "LICENSE", "extension/LICENSE")
    return filename


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(package(parser.parse_args().destination))
