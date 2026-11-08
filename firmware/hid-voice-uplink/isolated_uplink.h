#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Implemented in app_tts. Takes ownership of wav and frees it after play,
 * or when app_tts_cancel runs before playback starts. */
bool app_tts_play_wav(uint8_t *wav, size_t len);

void iso_uplink_configure(const char *https_url, const char *device_id, const char *credential, const char *ca_pem,
                          size_t ca_len, int use_ima);
void iso_uplink_on_capture(const uint8_t *wav, size_t len);
void iso_uplink_cancel(void);
