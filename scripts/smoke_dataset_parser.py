import io
import sys

import polars as pl
from ontology_platform.datasets.parser import validate

if __name__ == "__main__":
    print("Linux parser smoke", sys.platform, pl.__version__, flush=True)
    sources = {"csv": b"a\n1", "json": b'[{"a":1}]', "ndjson": b'{"a":1}'}
    file = io.BytesIO()
    pl.DataFrame({"a": [1]}).write_parquet(file)
    sources["parquet"] = file.getvalue()
    for format, content in sources.items():
        result = validate(io.BytesIO(content), format)
        assert result.get("row_count") == 1, result
        print("PASS", format, flush=True)
