/* Dynamic MPEG-1 video adapter for HP Prime G1 / 2025-09-15. */
#define __LINUX__ 1
#define PLM_NO_STDIO 1
#define PLM_BUFFER_DEFAULT_SIZE 4096
#define PLM_PRIME_INTEGER_VIDEO 1
#include <stddef.h>
#include <stdint.h>

static volatile uint32_t *g_context __attribute__((section(".data"))) =
    (volatile uint32_t *)(uintptr_t)1;

static uint32_t *mpeg_context(void)
{
    return (uint32_t *)(uintptr_t)g_context;
}

static void *mpeg_malloc(size_t size)
{
    uint32_t *context = mpeg_context();
    uint32_t used = context[21];
    uint32_t aligned = (uint32_t)((size + 7u) & ~7u);
    uint32_t start;
    if (!size || aligned < size || used > context[8] ||
        aligned > context[8] - used)
        return (void *)0;
    start = context[7] + used;
    if (start < context[7] || start + aligned < start)
        return (void *)0;
    context[21] = used + aligned;
    if (context[21] > context[22]) context[22] = context[21];
    context[23]++;
    return (void *)(uintptr_t)start;
}

static void mpeg_free(void *pointer) { (void)pointer; }
static void *mpeg_realloc(void *pointer, size_t size)
{
    uint32_t *context = mpeg_context();
    context[24]++;
    (void)pointer; (void)size;
    return (void *)0;
}

void *memcpy(void *destination, const void *source, size_t count)
{
    uint8_t *d = (uint8_t *)destination;
    const uint8_t *s = (const uint8_t *)source;
#ifndef PLM_PRIME_BYTE_COPY
    if ((((uintptr_t)d | (uintptr_t)s | count) & 3u) == 0) {
        uint32_t *dw = (uint32_t *)d;
        const uint32_t *sw = (const uint32_t *)s;
        while (count) { *dw++ = *sw++; count -= 4; }
        return destination;
    }
#endif
    while (count--) *d++ = *s++;
    return destination;
}

void *memmove(void *destination, const void *source, size_t count)
{
    uint8_t *d = (uint8_t *)destination;
    const uint8_t *s = (const uint8_t *)source;
    if (d == s) return destination;
    if (d < s) { while (count--) *d++ = *s++; }
    else { d += count; s += count; while (count--) *--d = *--s; }
    return destination;
}

void *memset(void *destination, int value, size_t count)
{
    uint8_t *d = (uint8_t *)destination;
    uint8_t byte = (uint8_t)value;
#ifndef PLM_PRIME_BYTE_COPY
    if ((((uintptr_t)d | count) & 3u) == 0) {
        uint32_t word = (uint32_t)byte * 0x01010101u;
        uint32_t *dw = (uint32_t *)d;
        while (count) { *dw++ = word; count -= 4; }
        return destination;
    }
#endif
    while (count--) *d++ = byte;
    return destination;
}

static int abs(int value) { return value < 0 ? -value : value; }

#define PLM_MALLOC(sz) mpeg_malloc(sz)
#define PLM_REALLOC(ptr, sz) mpeg_realloc((ptr), (sz))
#define PLM_FREE(ptr) mpeg_free(ptr)
#define PL_MPEG_IMPLEMENTATION
#include "../vendor/pl_mpeg/pl_mpeg.h"

#define ABI_VERSION    2u
#define CONTEXT_MAGIC  0x53545258u
#define RESULT_MAGIC   0x53545230u
#define COOKIE         0x5354524du
#define STATE_MAGIC    0x53545253u
#define SUCCESS        0x53540100u
#define FRAME_READY    0x53540101u
#define NEED_INPUT     0x53540102u
#define END_OF_STREAM  0x53540103u
#define DECODE_FAILED  0x5354e001u
#define RING_OVERFLOW  0x5354e002u
#define INIT_FAILED    0x5354e003u
#define UNSUPPORTED    0x5354e004u
#define OUT_OF_MEMORY  0x5354e005u
#define BAD_ARGS       0xffffffffu

#define COMMAND_INIT_STREAM   0u
#define COMMAND_FEED         1u
#define COMMAND_NEXT         2u
#define COMMAND_RESET        4u
#define COMMAND_RENDER       5u

#define OUTPUT_WIDTH 320u
#define OUTPUT_HEIGHT 240u
#define OUTPUT_BYTES (OUTPUT_WIDTH * OUTPUT_HEIGHT * 4u)
#define STAGING_BYTES 4096u
#define RING_BYTES 131072u
#ifdef PLM_PRIME_MIRRORED_RING
#define RING_STORAGE_BYTES (RING_BYTES * 2u)
#else
#define RING_STORAGE_BYTES RING_BYTES
#endif
#define RESULT_WORDS 48u
#define MIN_ARENA_BYTES 800u
#define MAX_ARENA_BYTES 0x01f00000u

static int range_ok(uint32_t address, uint32_t size)
{
    return address >= 0x30000000u && size && address + size >= address &&
           address + size <= 0x32000000u;
}

static int overlaps(uint32_t a, uint32_t an, uint32_t b, uint32_t bn)
{
    return a < b + bn && b < a + an;
}

static uint32_t rgb_pixel(uint8_t y, int rd, int gd, int bd)
{
    int yy = ((int)y - 16) * 76309 >> 16;
    int red = yy + rd, green = yy - gd, blue = yy + bd;
    if (red < 0) red = 0; else if (red > 255) red = 255;
    if (green < 0) green = 0; else if (green > 255) green = 255;
    if (blue < 0) blue = 0; else if (blue > 255) blue = 255;
    return ((uint32_t)red << 16) | ((uint32_t)green << 8) | (uint32_t)blue;
}

static void chroma_delta(uint8_t cb, uint8_t cr, int *rd, int *gd, int *bd)
{
    int cbv = (int)cb - 128, crv = (int)cr - 128;
    *rd = (crv * 104597) >> 16;
    *gd = (cbv * 25674 + crv * 53278) >> 16;
    *bd = (cbv * 132201) >> 16;
}

static void convert_identity(const plm_frame_t *frame, uint32_t *output)
{
    unsigned int x, y;
    for (y = 0; y < OUTPUT_HEIGHT; y += 2) {
        const uint8_t *y0 = frame->y.data + y * frame->y.width;
        const uint8_t *y1 = y0 + frame->y.width;
        const uint8_t *cb = frame->cb.data + (y >> 1) * frame->cb.width;
        const uint8_t *cr = frame->cr.data + (y >> 1) * frame->cr.width;
        uint32_t *out0 = output + y * OUTPUT_WIDTH;
        uint32_t *out1 = out0 + OUTPUT_WIDTH;
        for (x = 0; x < OUTPUT_WIDTH; x += 2) {
            unsigned int ci = x >> 1;
            int rd, gd, bd;
            chroma_delta(cb[ci], cr[ci], &rd, &gd, &bd);
            out0[x] = rgb_pixel(y0[x], rd, gd, bd);
            out0[x + 1] = rgb_pixel(y0[x + 1], rd, gd, bd);
            out1[x] = rgb_pixel(y1[x], rd, gd, bd);
            out1[x + 1] = rgb_pixel(y1[x + 1], rd, gd, bd);
        }
    }
}

static void convert_scaled(const plm_frame_t *frame, uint32_t *output,
                           const uint32_t *context)
{
    uint32_t sx = context[30], sy = context[31];
    uint32_t sw = context[32], sh = context[33];
    uint32_t dx = context[34], dy = context[35];
    uint32_t dw = context[36], dh = context[37];
    uint32_t oy, ox;
    if (sx == 0 && sy == 0 && sw == 320 && sh == 240 &&
        dx == 0 && dy == 0 && dw == 320 && dh == 240) {
        convert_identity(frame, output);
        return;
    }
    for (oy = 0; oy < dh; oy++) {
        uint32_t source_y = sy + (oy * sh) / dh;
        const uint8_t *luma = frame->y.data + source_y * frame->y.width;
        const uint8_t *cb = frame->cb.data + (source_y >> 1) * frame->cb.width;
        const uint8_t *cr = frame->cr.data + (source_y >> 1) * frame->cr.width;
        uint32_t *row = output + (dy + oy) * OUTPUT_WIDTH + dx;
        uint32_t previous_chroma = 0xffffffffu;
        int rd = 0, gd = 0, bd = 0;
        for (ox = 0; ox < dw; ox++) {
            uint32_t source_x = sx + (ox * sw) / dw;
            uint32_t ci = source_x >> 1;
            if (ci != previous_chroma) {
                chroma_delta(cb[ci], cr[ci], &rd, &gd, &bd);
                previous_chroma = ci;
            }
            row[ox] = rgb_pixel(luma[source_x], rd, gd, bd);
        }
    }
}

static int state_valid(uint32_t *context)
{
    uint32_t arena = context[7], bytes = context[8];
    uint32_t buffer = context[26], video = context[27];
    return context[25] == STATE_MAGIC && buffer && video &&
           buffer >= arena && buffer + 4u <= arena + bytes &&
           video >= arena && video + 4u <= arena + bytes;
}

static void result_base(uint32_t *context, uint32_t status)
{
    context[12] = RESULT_MAGIC;
    context[13] = status;
}

static void buffer_stats(uint32_t *context, plm_buffer_t *buffer)
{
    context[19] = (uint32_t)plm_buffer_tell(buffer);
    context[20] = (uint32_t)buffer->length;
}

static int geometry_ok(const uint32_t *c)
{
    return c[14] && c[14] <= 4095u && c[15] && c[15] <= 4095u &&
           c[16] >= 1u && c[16] <= 8u && c[29] >= 1u && c[29] <= 14u &&
           c[32] && c[33] && c[36] && c[37] &&
           c[30] + c[32] <= c[14] && c[31] + c[33] <= c[15] &&
           c[34] + c[36] <= OUTPUT_WIDTH &&
           c[35] + c[37] <= OUTPUT_HEIGHT;
}

static int validate_layout(uint32_t *context)
{
    uint32_t context_address = (uint32_t)(uintptr_t)context;
    uint32_t addresses[4], sizes[4];
    unsigned int i, j;
    if (!context || ((uintptr_t)context & 3u) ||
        !range_ok(context_address, RESULT_WORDS * 4u) ||
        context[0] != CONTEXT_MAGIC || context[40] != ABI_VERSION ||
        !geometry_ok(context))
        return 0;
    addresses[0] = context[1]; sizes[0] = context[2];
    addresses[1] = context[3]; sizes[1] = context[4];
    addresses[2] = context[5]; sizes[2] = context[6];
    addresses[3] = context[7]; sizes[3] = context[8];
    if ((addresses[0] | addresses[1] | addresses[2] | addresses[3]) & 3u ||
        sizes[0] != STAGING_BYTES || sizes[1] != RING_STORAGE_BYTES ||
        sizes[2] != OUTPUT_BYTES || sizes[3] < MIN_ARENA_BYTES ||
        sizes[3] > MAX_ARENA_BYTES)
        return 0;
    for (i = 0; i < 4; i++) {
        if (!range_ok(addresses[i], sizes[i]) ||
            overlaps(context_address, RESULT_WORDS * 4u,
                     addresses[i], sizes[i])) return 0;
        for (j = i + 1; j < 4; j++)
            if (overlaps(addresses[i], sizes[i], addresses[j], sizes[j]))
                return 0;
    }
    return 1;
}

static uint32_t fail(uint32_t *context, uint32_t code,
                     uint32_t status, uint32_t detail)
{
    context[12] = RESULT_MAGIC;
    context[13] = status;
    context[39] = detail;
    return code;
}

static uint32_t render_frame(uint32_t *context, plm_frame_t *frame)
{
    if (!frame) return fail(context, DECODE_FAILED, 3, 11);
    convert_scaled(frame, (uint32_t *)(uintptr_t)context[5], context);
    context[43]++;
    context[13] = 0;
    return FRAME_READY;
}

uint32_t mpeg_stream_main(uint32_t *context, uint32_t cookie)
{
    plm_buffer_t *buffer;
    plm_video_t *video;
    plm_frame_t *frame;
    uint32_t command;
    if (!context || cookie != COOKIE || !validate_layout(context))
        return BAD_ARGS;
    g_context = context;
    command = context[9];

    if (command == COMMAND_INIT_STREAM) {
        if (context[25] == STATE_MAGIC) return BAD_ARGS;
        context[17] = context[18] = context[19] = context[20] = 0;
        context[21] = context[22] = context[23] = context[24] = 0;
        context[25] = context[26] = context[27] = 0;
        context[38] = context[39] = context[42] = context[43] = context[44] = 0;
        memset((void *)(uintptr_t)context[5], 0, OUTPUT_BYTES);
        buffer = (plm_buffer_t *)mpeg_malloc(sizeof(plm_buffer_t));
        if (!buffer) return fail(context, OUT_OF_MEMORY, 8, 1);
        memset(buffer, 0, sizeof(*buffer));
        buffer->capacity = RING_BYTES;
        buffer->discard_read_bytes = TRUE;
        buffer->bytes = (uint8_t *)(uintptr_t)context[3];
        buffer->mode = PLM_BUFFER_MODE_RING;
        video = plm_video_create_with_buffer(buffer, TRUE);
        if (!video) return fail(context, OUT_OF_MEMORY, 8, 2);
        context[25] = STATE_MAGIC;
        context[26] = (uint32_t)(uintptr_t)buffer;
        context[27] = (uint32_t)(uintptr_t)video;
        result_base(context, 0);
        buffer_stats(context, buffer);
        return SUCCESS;
    }

    if (command == COMMAND_RESET) {
        if (!state_valid(context)) return BAD_ARGS;
        plm_video_destroy((plm_video_t *)(uintptr_t)context[27]);
        context[25] = context[26] = context[27] = context[42] = 0;
        result_base(context, 0);
        return SUCCESS;
    }

    if (!state_valid(context)) return BAD_ARGS;
    buffer = (plm_buffer_t *)(uintptr_t)context[26];
    video = (plm_video_t *)(uintptr_t)context[27];

    if (command == COMMAND_FEED) {
        uint32_t count = context[10];
        if (count > STAGING_BYTES || context[11] > 1u || context[38])
            return fail(context, BAD_ARGS, 7, 3);
        plm_buffer_discard_read_bytes(buffer);
        if (count > buffer->capacity - buffer->length)
            return fail(context, RING_OVERFLOW, 6, buffer->length);
        if (count && plm_buffer_write(
                buffer, (uint8_t *)(uintptr_t)context[1], count) != count)
            return fail(context, RING_OVERFLOW, 6, buffer->length);
        context[18] += count;
        if (context[11]) {
            plm_buffer_signal_end(buffer);
            buffer->has_ended = TRUE;
            context[38] = 1;
        }
        result_base(context, 0);
        buffer_stats(context, buffer);
        return SUCCESS;
    }

    if (command == COMMAND_RENDER) {
        frame = (plm_frame_t *)(uintptr_t)context[42];
        if (!frame || (uint32_t)(uintptr_t)frame < context[7] ||
            (uint32_t)(uintptr_t)frame + sizeof(*frame) > context[7] + context[8])
            return fail(context, DECODE_FAILED, 3, 10);
        return render_frame(context, frame);
    }

    if (command == COMMAND_NEXT) {
        if (!plm_video_has_header(video)) {
            buffer_stats(context, buffer);
            if (video->allocation_failed)
                return fail(context, OUT_OF_MEMORY, 8, context[8]);
            if (buffer->has_ended)
                return fail(context, DECODE_FAILED, 3, 4);
            return fail(context, NEED_INPUT, 5, 5);
        }
        if ((uint32_t)video->width != context[14] ||
            (uint32_t)video->height != context[15] ||
            (uint32_t)video->rate_code != context[16] ||
            (uint32_t)video->aspect_code != context[29])
            return fail(context, UNSUPPORTED, 2, 6);
        frame = plm_video_decode(video);
        buffer_stats(context, buffer);
        if (!frame) {
            if (buffer->has_ended) {
                if (!context[17]) return fail(context, DECODE_FAILED, 3, 7);
                return fail(context, END_OF_STREAM, 4, 0);
            }
            return fail(context, NEED_INPUT, 5, 8);
        }
        context[17]++;
        context[42] = (uint32_t)(uintptr_t)frame;
        if (context[41]) return render_frame(context, frame);
        context[44]++;
        context[13] = 0;
        return FRAME_READY;
    }
    return BAD_ARGS;
}
