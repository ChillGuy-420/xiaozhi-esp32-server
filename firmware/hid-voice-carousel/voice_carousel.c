#include "voice_carousel.h"

void voice_carousel_init(voice_carousel_t *carousel) {
    carousel->index = 0;
    carousel->shown_since_ms = 0;
    carousel->decoded_once = 0;
    carousel->dwell_pending = 1;
}

void voice_carousel_mark_decoded(voice_carousel_t *carousel) {
    carousel->decoded_once = 1;
}

int voice_carousel_frame(const voice_carousel_t *carousel, ui_mode_t mode, int voice_screen_visible) {
    if (!carousel->decoded_once || mode != UI_MODE_VOICE || !voice_screen_visible) {
        return -1;
    }
    if (carousel->index < 0 || carousel->index >= VOICE_FRAME_COUNT) {
        return -1;
    }
    return carousel->index;
}

int voice_carousel_tick(voice_carousel_t *carousel, ui_mode_t mode, int voice_screen_visible, uint32_t now_ms) {
    if (voice_carousel_frame(carousel, mode, voice_screen_visible) < 0) {
        carousel->dwell_pending = 1;
        return -1;
    }
    if (carousel->dwell_pending) {
        carousel->dwell_pending = 0;
        carousel->shown_since_ms = now_ms;
        return carousel->index;
    }
    if ((uint32_t)(now_ms - carousel->shown_since_ms) >= VOICE_CAROUSEL_MS) {
        carousel->index = (carousel->index + 1) % VOICE_FRAME_COUNT;
        carousel->shown_since_ms = now_ms;
    }
    return carousel->index;
}
