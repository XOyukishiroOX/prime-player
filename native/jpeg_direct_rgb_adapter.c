/* Experimental Prime adapter: JPEGDEC writes display-ready 0x00RRGGBB directly. */
#define __LINUX__ 1
#include <stddef.h>
#include <stdint.h>
#include "JPEGDEC.h"

void *memcpy(void *destination, const void *source, size_t count)
{
    uint8_t *d = (uint8_t *)destination;
    const uint8_t *s = (const uint8_t *)source;
    while (count--) *d++ = *s++;
    return destination;
}

void *memset(void *destination, int value, size_t count)
{
    uint8_t *d = (uint8_t *)destination;
    while (count--) *d++ = (uint8_t)value;
    return destination;
}

#include "jpeg_prime.inl"

#define CONTEXT_MAGIC 0x4a504358u
#define RESULT_MAGIC  0x4a504c30u
#define COOKIE        0x4a504547u
#define SUCCESS       0x4a500100u
#define BAD_ARGS      0xffffffffu
#define OPEN_FAILED   0x4a50e001u
#define UNSUPPORTED   0x4a50e002u
#define DECODE_FAILED 0x4a50e003u
#define WIDTH         320u
#define HEIGHT        240u
#define OUTPUT_BYTES  (WIDTH * HEIGHT * 4u)

const uint32_t jpeg_probe_workspace_bytes = sizeof(JPEGIMAGE);

static int range_ok(uint32_t address, uint32_t size)
{
    return address >= 0x30080000u && size && address + size >= address &&
           address + size <= 0x32000000u;
}

static int overlaps(uint32_t a, uint32_t an, uint32_t b, uint32_t bn)
{
    return a < b + bn && b < a + an;
}

uint32_t jpeg_probe_main(uint32_t *context, uint32_t cookie)
{
    uint32_t input, input_bytes, output, output_bytes, workspace, workspace_bytes;
    JPEGIMAGE *jpeg;
    int opened, decoded;

    if (!context || ((uintptr_t)context & 3u) || cookie != COOKIE ||
        !range_ok((uint32_t)(uintptr_t)context, 28u * 4u) ||
        context[0] != CONTEXT_MAGIC || context[7] != COOKIE)
        return BAD_ARGS;
    input = context[1]; input_bytes = context[2];
    output = context[3]; output_bytes = context[4];
    workspace = context[5]; workspace_bytes = context[6];
    if ((input | output | workspace) & 3u || input_bytes < 256u || input_bytes > 65536u ||
        output_bytes != OUTPUT_BYTES || workspace_bytes < sizeof(JPEGIMAGE) ||
        !range_ok(input, input_bytes) || !range_ok(output, output_bytes) ||
        !range_ok(workspace, workspace_bytes) ||
        overlaps(input, input_bytes, output, output_bytes) ||
        overlaps(input, input_bytes, workspace, workspace_bytes) ||
        overlaps(output, output_bytes, workspace, workspace_bytes))
        return BAD_ARGS;

    jpeg = (JPEGIMAGE *)(uintptr_t)workspace;
    context[8] = RESULT_MAGIC;
    context[9] = 1u;
    context[10] = context[11] = context[12] = context[13] = 0u;
    context[14] = context[15] = context[16] = context[17] = 0u;
    context[18] = context[19] = 0u;
    context[20] = (uint32_t)sizeof(JPEGIMAGE);
    opened = JPEG_openRAM(jpeg, (uint8_t *)(uintptr_t)input, (int)input_bytes, NULL);
    context[10] = (uint32_t)JPEG_getWidth(jpeg);
    context[11] = (uint32_t)JPEG_getHeight(jpeg);
    context[12] = (uint32_t)JPEG_getBpp(jpeg);
    context[13] = (uint32_t)JPEG_getSubSample(jpeg);
    context[14] = (uint32_t)jpeg->ucMode;
    context[15] = (uint32_t)JPEG_getLastError(jpeg);
    if (!opened) {
        context[9] = 2u;
        return OPEN_FAILED;
    }
    if (jpeg->ucMode != 0xc0 || context[10] != WIDTH || context[11] != HEIGHT ||
        context[12] != 24u) {
        context[9] = 3u;
        return UNSUPPORTED;
    }
    JPEG_setPixelType(jpeg, RGB8888);
    JPEG_setFramebuffer(jpeg, (void *)(uintptr_t)output);
    decoded = JPEG_decode(jpeg, 0, 0, 0);
    context[15] = (uint32_t)JPEG_getLastError(jpeg);
    if (!decoded || context[15] != JPEG_SUCCESS) {
        context[9] = 4u;
        return DECODE_FAILED;
    }

    /* The build-only JPEGDEC patch already emitted Prime 0x00RRGGBB words. */
    context[9] = 0u;
    context[16] = 0u;
    context[17] = ((uint32_t *)(uintptr_t)output)[0];
    context[18] = ((uint32_t *)(uintptr_t)output)[(HEIGHT / 2u) * WIDTH + WIDTH / 2u];
    context[19] = ((uint32_t *)(uintptr_t)output)[WIDTH * HEIGHT - 1u];
    return SUCCESS;
}
