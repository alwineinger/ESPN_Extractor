# ESPN Extractor – Usage

This project **uses** the excellent
[`espn-api`](https://github.com/cwendt94/espn-api/) library under the hood.

## Private leagues

Provide two cookie values as environment variables:

- `ESPN_S2` → your `espn_s2` cookie
- `SWID` → your `swid` cookie (format `{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}`)

```bash
export ESPN_S2="AECp.........................."
export SWID="{12345678-90AB-CDEF-1234-567890ABCDEF}"