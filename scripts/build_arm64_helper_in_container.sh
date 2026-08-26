#!/bin/sh
set -eu

# Run inside the pinned Debian container documented in helper/build/README.md:
# docker run --rm --network=bridge \
#   -e HELPER_VERSION=0.8.0 \
#   -v "$PWD:/source:ro" -v "/absolute/output:/output" \
#   debian@sha256:1710bde34461551a19a47c787885ec9ad7058d9a5bead2affb8d088fa2f8502b \
#   /bin/sh /source/scripts/build_arm64_helper_in_container.sh

SOURCE_ROOT=/source
OUTPUT_ROOT=/output
HELPER_VERSION=${HELPER_VERSION:?HELPER_VERSION must match the integration release}
AOSP_COMMIT=070571b455076f77a01c7b07154a15e545d2b428
APEX_SHA256=83bf0dce249728dae48149b80d28b48115c54adad95a352120d58a6ac669d1fc
APEX_URL="https://android.googlesource.com/platform/prebuilts/runtime/+/${AOSP_COMMIT}/mainline/runtime/apex/com.android.runtime-arm64.apex?format=TEXT"

test -f "$SOURCE_ROOT/helper/src/frame_probe.c"
test -f "$SOURCE_ROOT/helper/src/probe_libraries.c"
mkdir -p "$OUTPUT_ROOT"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    ca-certificates clang curl e2fsprogs erofs-utils lld python3 unzip

BUILD_ROOT=$(mktemp -d)
trap 'rm -rf "$BUILD_ROOT"' EXIT INT TERM

curl -fsSL "$APEX_URL" -o "$BUILD_ROOT/runtime.apex.base64"
base64 -d "$BUILD_ROOT/runtime.apex.base64" > "$BUILD_ROOT/runtime.apex"
echo "$APEX_SHA256  $BUILD_ROOT/runtime.apex" | sha256sum -c -
mkdir -p "$BUILD_ROOT/apex" "$BUILD_ROOT/payload"
unzip -q "$BUILD_ROOT/runtime.apex" -d "$BUILD_ROOT/apex"
if ! fsck.erofs --extract="$BUILD_ROOT/payload" \
    "$BUILD_ROOT/apex/apex_payload.img"; then
    debugfs -R "rdump / $BUILD_ROOT/payload" "$BUILD_ROOT/apex/apex_payload.img"
fi

LIBRARY_ROOT="$BUILD_ROOT/payload/lib64/bionic"
if test ! -f "$LIBRARY_ROOT/libc.so"; then
    LIBRARY_ROOT="$BUILD_ROOT/payload/lib64"
fi
for runtime_file in libc.so libdl.so libm.so; do
    test -f "$LIBRARY_ROOT/$runtime_file"
done
test -f "$BUILD_ROOT/payload/bin/linker64"

mkdir -p "$BUILD_ROOT/bin" "$BUILD_ROOT/runtime/bin" "$BUILD_ROOT/runtime/lib64"
cp "$BUILD_ROOT/payload/bin/linker64" "$BUILD_ROOT/runtime/bin/linker64"
cp "$LIBRARY_ROOT/libc.so" "$BUILD_ROOT/runtime/lib64/libc.so"
cp "$LIBRARY_ROOT/libdl.so" "$BUILD_ROOT/runtime/lib64/libdl.so"
cp "$LIBRARY_ROOT/libm.so" "$BUILD_ROOT/runtime/lib64/libm.so"

COMMON_FLAGS="--target=aarch64-linux-android35 -std=c11 -O2 -fPIE -ffreestanding -fno-stack-protector -nostdlib -fuse-ld=lld"
LINK_FLAGS="-pie -Wl,-e,_start -Wl,--dynamic-linker=/runtime/bin/linker64 -Wl,--build-id=none -Wl,-z,noexecstack -Wl,-z,relro,-z,now -L$LIBRARY_ROOT -lc -ldl"

# shellcheck disable=SC2086
clang $COMMON_FLAGS "$SOURCE_ROOT/helper/src/probe_libraries.c" \
    $LINK_FLAGS -o "$BUILD_ROOT/bin/probe_libraries"
# shellcheck disable=SC2086
clang $COMMON_FLAGS "$SOURCE_ROOT/helper/src/frame_probe.c" \
    $LINK_FLAGS -o "$BUILD_ROOT/bin/frame_probe"
# shellcheck disable=SC2086
clang $COMMON_FLAGS -DSNAPSHOT_CAPTURE "$SOURCE_ROOT/helper/src/frame_probe.c" \
    $LINK_FLAGS -o "$BUILD_ROOT/bin/snapshot_capture"
# shellcheck disable=SC2086
clang $COMMON_FLAGS -DSTREAM_CAPTURE "$SOURCE_ROOT/helper/src/frame_probe.c" \
    $LINK_FLAGS -o "$BUILD_ROOT/bin/stream_capture"

NOTICE="$BUILD_ROOT/apex/assets/NOTICE.html.gz"
test -f "$NOTICE"
python3 "$SOURCE_ROOT/scripts/build_helper_runtime.py" \
    --version "$HELPER_VERSION" \
    --frame-probe "$BUILD_ROOT/bin/frame_probe" \
    --snapshot-capture "$BUILD_ROOT/bin/snapshot_capture" \
    --stream-capture "$BUILD_ROOT/bin/stream_capture" \
    --library-probe "$BUILD_ROOT/bin/probe_libraries" \
    --runtime-root "$BUILD_ROOT/runtime" \
    --aosp-notice "$NOTICE" \
    --output "$OUTPUT_ROOT/owlet-cam-helper-aarch64.tar.gz"

python3 "$SOURCE_ROOT/scripts/build_helper_runtime.py" \
    --version "$HELPER_VERSION" \
    --frame-probe "$BUILD_ROOT/bin/frame_probe" \
    --snapshot-capture "$BUILD_ROOT/bin/snapshot_capture" \
    --stream-capture "$BUILD_ROOT/bin/stream_capture" \
    --library-probe "$BUILD_ROOT/bin/probe_libraries" \
    --runtime-root "$BUILD_ROOT/runtime" \
    --aosp-notice "$NOTICE" \
    --output "$OUTPUT_ROOT/.owlet-cam-helper-aarch64.repro.tar.gz"
cmp "$OUTPUT_ROOT/owlet-cam-helper-aarch64.tar.gz" \
    "$OUTPUT_ROOT/.owlet-cam-helper-aarch64.repro.tar.gz"
rm "$OUTPUT_ROOT/.owlet-cam-helper-aarch64.repro.tar.gz"

sha256sum "$OUTPUT_ROOT/owlet-cam-helper-aarch64.tar.gz" \
    > "$OUTPUT_ROOT/owlet-cam-helper-aarch64.tar.gz.sha256"
