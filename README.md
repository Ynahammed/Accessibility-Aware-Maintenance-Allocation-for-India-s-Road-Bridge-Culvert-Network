# Accessibility-Aware Maintenance Allocation

A research prototype for prioritizing road, bridge, and culvert maintenance by
the effect failures have on people's access to health facilities and schools.
It compares condition-first maintenance with network-aware allocation, where
the consequence of a failure depends on which other routes and structures fail
at the same time.

> **Research status:** This is not a production planning tool, and its
> allocation results are not recommendations for a real Indian district.
> India-specific rainfall, rural-road, and asset-condition inputs are not
> currently available in this environment. Allocation experiments therefore
> use seeded synthetic districts and explicitly recorded assumptions.

## Run the interactive demo

The demo serves a local web page and a small Python API. Python 3.12 was used
to verify the project. From the repository root, create and activate a virtual
environment, install the dependencies, and start the server:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install numpy networkx pandas scipy scikit-learn geopandas osmnx shapely imdlib pyarrow pytest
python demo\server.py
```

Open <http://127.0.0.1:8737/> in a browser. To select a different local port:

```powershell
python demo\server.py --host 127.0.0.1 --port 8738
```

The live allocation lab compares five policies on shared scenario draws
(common random numbers), maps their first-year plans, and reports access-loss
and paired-comparison metrics. The non-additivity explorer lets you fail
structures on parallel routes and compare the resulting joint accessibility
loss with the sum of individual losses. The evidence panels display the saved
E1, E3, E4, and E8 experiment results, data availability, QA, and the
assumptions register.

The demo API is also available locally:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/evidence` | Saved experiment results, input availability, QA, and assumptions |
| `POST` | `/api/run` | Run a paired allocation experiment on a synthetic district |
| `POST` | `/api/loss` | Calculate accessibility loss for a chosen set of failed structures |

The `POST` endpoints accept JSON. The page itself provides example inputs and
renders their results.

## Deploy to Vercel

Import the repository into Vercel with the project root set to the repository
root. Vercel discovers the root `app.py` FastAPI entrypoint and installs the
dependencies in `requirements.txt`. The FastAPI app serves the demo page and
implements its API routes; no rewrite configuration or separate build command
is needed. Push to the connected Git branch or redeploy the latest commit;
then open the deployment URL.

The API routes reuse the same research functions as the local demo:
`GET /api/evidence`, `POST /api/run`, and `POST /api/loss`. `.vercelignore`
omits local environments and raw source datasets that the app does not
need; the small saved experiment results and QA reports remain included.

## What the current evidence says

The application marks evidence by provenance; the distinctions matter when
interpreting the results:

| Input or result | Current evidence |
| --- | --- |
| Bridge deterioration | Real US FHWA National Bridge Inventory (NBI) observations: 18 files for AL, CA, and TX, 2018–2023; 582,014 panel rows in the saved E1 run. These are not Indian asset records. |
| Road graph | Real OpenStreetMap road graph for Alappuzha: 1,972 nodes, 2,361 edges, and one connected component. The graph has 74 bridge-tagged edges and no culvert-tagged edges. |
| Habitations and facilities on the real graph | Not yet available in the local build: the QA report has zero habitation points and zero health facilities or schools, so real-network accessibility loss cannot yet be computed. |
| IMD rainfall and PMGSY roads | Acquisition was blocked from this environment; these are not used as observed inputs in the allocation results. |
| State PWD / IBMS condition records | Unavailable without a data request. |
| Allocation experiments (E3, E4, E8) | Seeded synthetic districts, synthetic scenarios, and assumption-register parameters; results are simulator experiments, not observed Indian-district outcomes. |

The assumptions register in [`docs/assumptions.md`](docs/assumptions.md)
labels its quantities as assumed or fitted and records their ranges and
sources. The live demo and experiment outputs retain these provenance caveats.

Two examples help interpret the saved results:

- In E1, evaluated on real US NBI histories, the age-class Markov baseline has
  a lower test log-loss than the gradient-boosting model (0.1636 vs. 0.1772).
  The current evidence therefore does **not** support a claim that the ML model
  outperforms the Markov baseline.
- In E4's synthetic, two-parallel-route setting, mean person-days lost are
  15,579 for the additive MILP and 10,795 for the network-aware policy. This
  illustrates the intended non-additivity mechanism under that experiment's
  assumptions; it is not a real-world impact estimate.

## Project layout

```text
src/rra/          Research modules: network, accessibility, deterioration,
                  hazards, costs, optimization, simulation, and evaluation
demo/             Browser-based interactive demo and local API server
experiments/      Seeded E1, E3, E4, and E8 scripts, configurations, and results
data/raw/         Included NBI source files and OSM graph inputs
data/processed/   Network QA reports and processed structure data
scripts/          Data download, network construction/QA, and assumptions tools
docs/             Assumptions register documentation
tests/            Unit and integration tests
```

## Run the tests

With the environment and dependencies installed, run the test suite from the
repository root:

```powershell
python -m pytest -q
```

The test bootstrap adds `src/` to the import path, so an editable package
install is not required for the tests or demo.
