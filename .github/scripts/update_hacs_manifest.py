"""Set the integration manifest version, used at release time to match the git tag.

The committed manifest keeps a placeholder version; the release workflow runs this to
stamp the real version into the manifest that goes inside the HACS zip asset. Key order
is preserved (json keeps insertion order), so the hassfest-required "domain, name first"
ordering is not disturbed.
"""

import json
import os
import sys

MANIFEST = f"{os.getcwd()}/custom_components/tuya_eboard/manifest.json"


def update_manifest() -> None:
    """Write the --version value (tag, with any leading 'v' stripped) into the manifest."""
    version = "0.0.0"
    for index, value in enumerate(sys.argv):
        if value in ("--version", "-V"):
            version = sys.argv[index + 1]
    version = version.lstrip("v")

    with open(MANIFEST) as manifestfile:
        manifest = json.load(manifestfile)

    manifest["version"] = version

    with open(MANIFEST, "w") as manifestfile:
        json.dump(manifest, manifestfile, indent=2)
        manifestfile.write("\n")


if __name__ == "__main__":
    update_manifest()
