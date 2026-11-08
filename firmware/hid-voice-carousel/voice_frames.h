#pragma once

#include "lvgl.h"
#include <stdbool.h>

/* Full-screen voice pictures. Desk wallpaper is not referenced. */
void voice_frames_attach(lv_obj_t *voice_screen);
void voice_frames_set_shown(bool voice_screen_visible);
