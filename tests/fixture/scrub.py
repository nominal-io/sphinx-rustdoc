"""Remove machine-specific paths from rustdoc JSON before it's committed as the tests' fixture.

rustdoc records where each external crate's metadata lives on the machine that built the JSON,
which names that machine's user. sphinx-rustdoc doesn't read those paths.
"""

import json
import sys
from pathlib import Path

source, target = Path(sys.argv[1]), Path(sys.argv[2])
doc = json.loads(source.read_text(encoding="utf-8"))
for crate in doc["external_crates"].values():
    crate["path"] = ""
target.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
