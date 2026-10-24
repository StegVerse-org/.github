python -m unittest tests.test_origin_attestation_tvc_conformance -v 2>&1 | tee conformance.log
python - <<'PY'
text = open("conformance.log").read()
skipped = "skipped" in text
assert "FAILED" not in text, "the conformance module failed rather than skipped"
state = "UNPROVEN_HERE_TVC_NOT_CHECKED_OUT" if skipped else "PROVEN_AGAINST_TVC"
print("TVC_CONFORMANCE=" + state)
if skipped:
    print("A skipped conformance run is unproven, not passed. It runs where "
          "TVC is present: set STEGVERSE_TVC_ROOT. TV/TVC also runs the "
          "exchange against this consumer in its own CI, where "
          "tv_consumer_integration_observed is true as of "
          "StegVerse-Labs/tvc@1e6c909 -- so the exchange is proven on the "
          "side that holds the key, and this skip reports only what this "
          "CI did not prove.")
PY
