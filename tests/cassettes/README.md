# `tests/cassettes/`

Convention for any test that ever needs to exercise a real model-provider call (`00` SS7,
security baseline Task 52 item 8).

- Nothing in this test suite currently makes a live network call -- Phase 1's provider gateway
  is entirely shimmed (`ground_truth/_bok_shim.py`), by design (`00` R5, `$0` recurring cost).
  This directory exists so the moment a real gateway call lands, the pattern is already here.
- Any such test must be wrapped with [`vcrpy`](https://vcrpy.readthedocs.io/):

  ```python
  import vcr


  @vcr.use_cassette("tests/cassettes/<descriptive-name>.yaml")
  def test_something_that_calls_a_real_provider() -> None: ...
  ```

- Record the cassette once, against a real (rate-limited, free-tier) call, then commit it.
  Every subsequent run replays the recorded interaction -- CI never depends on live network
  access or spends quota re-running the same test.
- **Never commit a cassette containing a real API key or bearer token.** Configure the
  recording so the `Authorization` header (or equivalent) is filtered before it is written to
  disk -- vcrpy's `filter_headers` option does this:

  ```python
  my_vcr = vcr.VCR(filter_headers=["authorization", "x-api-key"])
  ```

- `ground_truth/regression/smoke.py` is the nightly live smoke test harness this cassette
  convention exists alongside (`.github/workflows/nightly-smoke.yml`) -- it is intentionally
  *not* itself a cassette-replayed test, since its entire point is to catch a real provider
  going silent, which a cassette can only ever prove happened once.
