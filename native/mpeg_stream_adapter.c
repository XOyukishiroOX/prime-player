/* Fixed-memory streaming MPEG-1 video adapter for HP Prime G1. */
#define __LINUX__ 1
#define PLM_NO_STDIO 1
#define PLM_BUFFER_DEFAULT_SIZE 4096
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

static void mpeg_free(void *pointer)
{
    (void)pointer;
}

static void *mpeg_realloc(void *pointer, size_t size)
{
    uint32_t *context = mpeg_context();
    context[24]++;
    (void)pointer;
    (void)size;
    return (void *)0;
}

void *memcpy(void *destination, const void *source, size_t count)
{
    uint8_t *d = (uint8_t *)destination;
    const uint8_t *s = (const uint8_t *)source;
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
    while (count--) *d++ = (uint8_t)value;
    return destination;
}

static int abs(int value)
{
    return value < 0 ? -value : value;
}

#define PLM_MALLOC(sz) mpeg_malloc(sz)
#define PLM_REALLOC(ptr, sz) mpeg_realloc((ptr), (sz))
#define PLM_FREE(ptr) mpeg_free(ptr)
#define PL_MPEG_IMPLEMENTATION
#include "../vendor/pl_mpeg/pl_mpeg.h"

#define CONTEXT_MAGIC 0x53545258u
#define RESULT_MAGIC  0x53545230u
#define COOKIE        0x5354524du
#define STATE_MAGIC   0x53545253u
#define SUCCESS       0x53540100u
#define FRAME_READY   0x53540101u
#define NEED_INPUT    0x53540102u
#define END_OF_STREAM 0x53540103u
#define DECODE_FAILED 0x5354e001u
#define RING_OVERFLOW 0x5354e002u
#define INIT_FAILED   0x5354e003u
#define UNSUPPORTED   0x5354e004u
#define BAD_ARGS      0xffffffffu

#define COMMAND_INIT_STREAM 0u
#define COMMAND_FEED       1u
#define COMMAND_NEXT_2X2   2u
#define COMMAND_RESET      4u

#define WIDTH 320u
#define HEIGHT 240u
#define OUTPUT_BYTES (WIDTH * HEIGHT * 4u)
#define STAGING_BYTES 4096u
#define RING_BYTES 131072u
#define RESULT_WORDS 40u

static int range_ok(uint32_t address, uint32_t size)
{
    return address >= 0x30000000u && size && address + size >= address &&
           address + size <= 0x32000000u;
}

static int overlaps(uint32_t a, uint32_t an, uint32_t b, uint32_t bn)
{
    return a < b + bn && b < a + an;
}

static uint32_t pixel(uint8_t y, int red_delta, int green_delta,
                      int blue_delta)
{
    int yy = ((int)y - 16) * 76309 >> 16;
    int red = yy + red_delta;
    int green = yy - green_delta;
    int blue = yy + blue_delta;
    if (red < 0) red = 0; else if (red > 255) red = 255;
    if (green < 0) green = 0; else if (green > 255) green = 255;
    if (blue < 0) blue = 0; else if (blue > 255) blue = 255;
    return ((uint32_t)red << 16) | ((uint32_t)green << 8) | (uint32_t)blue;
}

static void convert_frame_2x2(const plm_frame_t *frame, uint32_t *output)
{
    unsigned int x, y;
    for (y = 0; y < HEIGHT; y += 2) {
        const uint8_t *y0 = frame->y.data + y * frame->y.width;
        const uint8_t *y1 = y0 + frame->y.width;
        const uint8_t *cb = frame->cb.data + (y >> 1) * frame->cb.width;
        const uint8_t *cr = frame->cr.data + (y >> 1) * frame->cr.width;
        uint32_t *out0 = output + y * WIDTH;
        uint32_t *out1 = out0 + WIDTH;
        for (x = 0; x < WIDTH; x += 2) {
            unsigned int ci = x >> 1;
            int cb_value = (int)cb[ci] - 128;
            int cr_value = (int)cr[ci] - 128;
            int red_delta = (cr_value * 104597) >> 16;
            int green_delta = (cb_value * 25674 + cr_value * 53278) >> 16;
            int blue_delta = (cb_value * 132201) >> 16;
            out0[x] = pixel(y0[x], red_delta, green_delta, blue_delta);
            out0[x + 1] = pixel(y0[x + 1], red_delta, green_delta, blue_delta);
            out1[x] = pixel(y1[x], red_delta, green_delta, blue_delta);
            out1[x + 1] = pixel(y1[x + 1], red_delta, green_delta, blue_delta);
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

static int validate_layout(uint32_t *context)
{
    uint32_t staging = context[1], staging_bytes = context[2];
    uint32_t ring = context[3], ring_bytes = context[4];
    uint32_t output = context[5], output_bytes = context[6];
    uint32_t arena = context[7], arena_bytes = context[8];
    uint32_t context_address = (uint32_t)(uintptr_t)context;
    if (!context || ((uintptr_t)context & 3u) ||
        !range_ok(context_address, RESULT_WORDS * 4u) ||
        context[0] != CONTEXT_MAGIC)
        return 0;
    if ((staging | ring | output | arena) & 3u ||
        staging_bytes != STAGING_BYTES || ring_bytes != RING_BYTES ||
        output_bytes != OUTPUT_BYTES || arena_bytes < 360000u ||
        !range_ok(staging, staging_bytes) || !range_ok(ring, ring_bytes) ||
        !range_ok(output, output_bytes) || !range_ok(arena, arena_bytes) ||
        overlaps(context_address, RESULT_WORDS * 4u, staging, staging_bytes) ||
        overlaps(context_address, RESULT_WORDS * 4u, ring, ring_bytes) ||
        overlaps(context_address, RESULT_WORDS * 4u, output, output_bytes) ||
        overlaps(context_address, RESULT_WORDS * 4u, arena, arena_bytes) ||
        overlaps(staging, staging_bytes, ring, ring_bytes) ||
        overlaps(staging, staging_bytes, output, output_bytes) ||
        overlaps(staging, staging_bytes, arena, arena_bytes) ||
        overlaps(ring, ring_bytes, output, output_bytes) ||
        overlaps(ring, ring_bytes, arena, arena_bytes) ||
        overlaps(output, output_bytes, arena, arena_bytes))
        return 0;
    return 1;
}

static uint32_t fail(uint32_t *context, uint32_t return_code,
                     uint32_t status, uint32_t detail)
{
    context[12] = RESULT_MAGIC;
    context[13] = status;
    context[39] = detail;
    return return_code;
}

uint32_t mpeg_stream_main(uint32_t *context, uint32_t cookie)
{
    plm_buffer_t *buffer;
    plm_video_t *video;
    plm_frame_t *frame;
    uint32_t command;

    if (!context || cookie != COOKIE || !validate_layout(context) ||
        context[7] == 0 || context[8] < 360000u)
        return BAD_ARGS;
    g_context = context;
    command = context[9];

    if (command == COMMAND_INIT_STREAM) {
        if (context[25] == STATE_MAGIC) return BAD_ARGS;
        context[21] = context[22] = context[23] = context[24] = 0;
        context[17] = context[18] = context[19] = context[20] = 0;
        context[38] = context[39] = 0;
        buffer = (plm_buffer_t *)mpeg_malloc(sizeof(plm_buffer_t));
        if (!buffer) return fail(context, INIT_FAILED, 1, 1);
        memset(buffer, 0, sizeof(*buffer));
        buffer->capacity = RING_BYTES;
        buffer->length = 0;
        buffer->total_size = 0;
        buffer->discard_read_bytes = TRUE;
        buffer->has_ended = FALSE;
        buffer->free_when_done = FALSE;
        buffer->bytes = (uint8_t *)(uintptr_t)context[3];
        buffer->mode = PLM_BUFFER_MODE_RING;
        video = plm_video_create_with_buffer(buffer, TRUE);
        if (!video) {
            plm_buffer_destroy(buffer);
            return fail(context, INIT_FAILED, 1, 2);
        }
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
        context[25] = context[26] = context[27] = 0;
        context[21] = context[22] = context[23] = context[24] = 0;
        context[17] = context[18] = context[19] = context[20] = 0;
        context[38] = context[39] = 0;
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
        if (count) {
            if (plm_buffer_write(buffer,
                                 (uint8_t *)(uintptr_t)context[1], count) != count)
                return fail(context, RING_OVERFLOW, 6, buffer->length);
            context[18] += count;
        }
        if (context[11]) {
            plm_buffer_signal_end(buffer);
            buffer->has_ended = TRUE;
            context[38] = 1;
        }
        result_base(context, 0);
        buffer_stats(context, buffer);
        return SUCCESS;
    }

    if (command == COMMAND_NEXT_2X2) {
        if (!plm_video_has_header(video)) {
            buffer_stats(context, buffer);
            if (buffer->has_ended)
                return fail(context, DECODE_FAILED, 3, 4);
            return fail(context, NEED_INPUT, 5, 5);
        }
        context[14] = (uint32_t)plm_video_get_width(video);
        context[15] = (uint32_t)plm_video_get_height(video);
        context[16] = (uint32_t)(plm_video_get_framerate(video) * 1000.0 + 0.5);
        if (context[14] != WIDTH || context[15] != HEIGHT ||
            context[16] != 25000u)
            return fail(context, UNSUPPORTED, 2, 6);
        frame = plm_video_decode(video);
        buffer_stats(context, buffer);
        if (!frame) {
            if (buffer->has_ended) {
                if (context[17] == 0)
                    return fail(context, DECODE_FAILED, 3, 7);
                return fail(context, END_OF_STREAM, 4, 0);
            }
            return fail(context, NEED_INPUT, 5, 8);
        }
        convert_frame_2x2(frame, (uint32_t *)(uintptr_t)context[5]);
        context[17]++;
        context[13] = 0;
        return FRAME_READY;
    }

    return BAD_ARGS;
}
