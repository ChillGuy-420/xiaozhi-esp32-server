#include "iso_voice.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;
static int releases;
static int posts;
static int plays;
static int cancels;
static int http_status = 200;
static int drop_response;
static uint8_t *played;
static size_t played_len;
static iso_voice_t *active;

static const char *kCa =
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBTESTCERTIFICATEONLYFORPOLICYCHECKNOTAREALPRIVATEKEYMATERIAL\n"
    "-----END CERTIFICATE-----\n";

static int post_wav(void *ctx, const uint8_t *wav, size_t len, uint8_t **resp, size_t *resp_len, int *status) {
    (void)ctx;
    if (memcmp(wav, "RIFF", 4) != 0 || memcmp(wav + 8, "WAVE", 4) != 0) {
        fprintf(stderr, "FAIL upload is not a wav\n");
        ++failures;
    }
    posts += 1;
    *status = http_status;
    if (drop_response || http_status != 200) {
        *resp = NULL;
        *resp_len = 0;
        return 0;
    }
    *resp = malloc(len);
    memcpy(*resp, wav, len);
    *resp_len = len;
    if (cancels) {
        iso_voice_cancel(active);
    }
    return 0;
}

static int play_wav(void *ctx, uint8_t *wav, size_t len) {
    (void)ctx;
    played = wav;
    played_len = len;
    plays += 1;
    return 0;
}

static void cancel_play(void *ctx) {
    (void)ctx;
    cancels += 1;
    free(played);
    played = NULL;
    played_len = 0;
}

static void release_capture(void *ctx) {
    (void)ctx;
    releases += 1;
}

static iso_voice_ops_t ops(void) {
    iso_voice_ops_t out = {0};
    out.post_wav = post_wav;
    out.play_wav = play_wav;
    out.cancel_play = cancel_play;
    out.release_capture = release_capture;
    return out;
}

static void reset_counters(void) {
    releases = posts = plays = cancels = 0;
    http_status = 200;
    drop_response = 0;
    free(played);
    played = NULL;
}

int main(void) {
    uint8_t capture[44];
    memset(capture, 0, sizeof(capture));
    memcpy(capture, "RIFF", 4);
    memcpy(capture + 8, "WAVE", 4);
    iso_voice_ops_t table = ops();
    iso_voice_t *voice = iso_voice_create(&table, "https://voice.example.test/xiaozhi/isolated/hid-voice",
                                          "isolated-device-credential", kCa, strlen(kCa));
    active = voice;
    if (iso_voice_submit(voice, capture, sizeof(capture), capture, sizeof(capture)) != 0 || plays != 1 ||
        releases != 1 || posts != 1 || played_len != sizeof(capture)) {
        fprintf(stderr, "FAIL success path releases=%d posts=%d plays=%d\n", releases, posts, plays);
        ++failures;
    }
    free(played);
    played = NULL;
    reset_counters();
    http_status = 401;
    if (iso_voice_submit(voice, capture, sizeof(capture), capture, sizeof(capture)) == 0 || plays != 0 ||
        releases != 1) {
        fprintf(stderr, "FAIL 401 still played\n");
        ++failures;
    }
    reset_counters();
    iso_voice_destroy(voice);
    voice = iso_voice_create(&table, "https://ntfy.sh/topic", "isolated-device-credential", kCa, strlen(kCa));
    active = voice;
    if (iso_voice_submit(voice, capture, sizeof(capture), capture, sizeof(capture)) == 0 || posts != 0 ||
        releases != 1 || plays != 0) {
        fprintf(stderr, "FAIL ntfy was contacted\n");
        ++failures;
    }
    iso_voice_destroy(voice);
    voice = iso_voice_create(&table, "https://voice.example.test/xiaozhi/isolated/hid-voice",
                             "isolated-device-credential", kCa, strlen(kCa));
    active = voice;
    reset_counters();
    drop_response = 0;
    http_status = 200;
    cancels = 1;
    if (iso_voice_submit(voice, capture, sizeof(capture), capture, sizeof(capture)) == 0 || plays != 0 ||
        releases != 1) {
        fprintf(stderr, "FAIL cancel during post still played\n");
        ++failures;
    }
    iso_voice_destroy(voice);
    if (failures) {
        fprintf(stderr, "%d failures\n", failures);
        return 1;
    }
    puts("iso voice ownership ok");
    return 0;
}
