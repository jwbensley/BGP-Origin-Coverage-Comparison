# BGP Route Origin Authorisation Comparison

This repo makes a three-way comparison of origin ASNs of prefixes as seen in the public DFZ, as defined in the IRR database ecosystem, and as defined in the RPKI.

This is achieved by:

* Downloading and parsing a full BGP table dump from a public MRT archive
* Downloading and parsing the IRR data from public IRR DBs
* Downloading and parsing the RPKI ROA data from a public RPKI cache
* Comparing the origin ASNs of each route in the DFZ/IRR/RPKI data

Prefix length is limit to /8 to /24 and /8 to /48.

## Results

The generated plots are stored in [plots/](plots/).

## Usage

```text
# You need uv to run the scripts.
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```text
# Download and compare the data
./compare.py

# Plot the results
./plot.py
```

`uv` is used for dependency management, which means that the python deps are automatically installed into a venv when the scripts are first run.

If you want to create a venv (e.g. for your IDE) without running the scripts:

```text
uv sync
```
