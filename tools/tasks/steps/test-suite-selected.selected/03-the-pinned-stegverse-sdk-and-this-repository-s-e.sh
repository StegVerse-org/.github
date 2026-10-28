set -eu
SDK_SHA=74d9b473aa415b06a9d550c28b2779a691b4ba32
curl -fsSL "https://github.com/StegVerse-org/StegVerse-SDK/archive/${SDK_SHA}.tar.gz" -o "$RUNNER_TEMP/stegverse-sdk.tgz"
mkdir "$RUNNER_TEMP/stegverse-sdk"
tar -xzf "$RUNNER_TEMP/stegverse-sdk.tgz" -C "$RUNNER_TEMP/stegverse-sdk" --strip-components=1
python -m pip install --quiet --no-deps "$RUNNER_TEMP/stegverse-sdk"
# pinned as required-verification.yml (#222) pins it: the runner's system
# jsonschema 4.10.3 equates a nested true with 1 in enum/const
python -m pip install --quiet "jsonschema==4.26.0"
