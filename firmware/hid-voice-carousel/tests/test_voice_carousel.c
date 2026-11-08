#include "voice_carousel.h"

#include <stdio.h>
#include <string.h>

static int failures = 0;

static void expect_int(const char *name, int got, int want) {
    if (got != want) {
        fprintf(stderr, "FAIL %s got %d want %d\n", name, got, want);
        ++failures;
    }
}

int main(void) {
    voice_carousel_t carousel;
    voice_carousel_init(&carousel);
    expect_int("hidden before decode", voice_carousel_tick(&carousel, UI_MODE_VOICE, 1, 1000), -1);

    voice_carousel_mark_decoded(&carousel);
    expect_int("voice frame 0", voice_carousel_tick(&carousel, UI_MODE_VOICE, 1, 1000), 0);
    expect_int("still 0 before 8s", voice_carousel_tick(&carousel, UI_MODE_VOICE, 1, 8999), 0);
    expect_int("advance at 8s", voice_carousel_tick(&carousel, UI_MODE_VOICE, 1, 9000), 1);

    int frozen = carousel.index;
    expect_int("desk shows no voice frame", voice_carousel_tick(&carousel, UI_MODE_DESK, 0, 20000), -1);
    expect_int("desk does not advance", carousel.index, frozen);
    expect_int("voice screen hidden does not advance", voice_carousel_tick(&carousel, UI_MODE_VOICE, 0, 30000), -1);
    expect_int("index unchanged while hidden", carousel.index, frozen);
    expect_int("resume same frame", voice_carousel_tick(&carousel, UI_MODE_VOICE, 1, 30000), frozen);

    if (VOICE_FRAME_BYTES != 460800) {
        fprintf(stderr, "FAIL frame size\n");
        ++failures;
    }
    const char *voice_names[] = {
        "voice-mode.rgb565",
        "voice-mode-2.rgb565",
        "voice-mode-3.rgb565",
        "voice-mode-4.rgb565",
        "voice-mode-5.rgb565",
    };
    for (int i = 0; i < VOICE_FRAME_COUNT; ++i) {
        if (strcmp(voice_names[i], "wallpaper.rgb565") == 0) {
            fprintf(stderr, "FAIL voice asset reused the desktop name\n");
            ++failures;
        }
    }

    if (failures != 0) {
        fprintf(stderr, "%d failures\n", failures);
        return 1;
    }
    puts("voice carousel ok");
    return 0;
}
