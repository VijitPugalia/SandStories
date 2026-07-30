// Dump RGB plus official libfreenect registered depth frames from a fakenect recording.
// Build on the Kinect machine, then run through build/fakenect/fakenect.sh.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "libfreenect.h"
#include "libfreenect_sync.h"

static void write_rgb(const char *path, const uint8_t *data) {
    FILE *fp = fopen(path, "wb");
    if (!fp) {
        perror(path);
        exit(1);
    }
    fprintf(fp, "P6\n640 480\n255\n");
    fwrite(data, 640 * 480 * 3, 1, fp);
    fclose(fp);
}

static void write_depth(const char *path, const uint16_t *data) {
    FILE *fp = fopen(path, "wb");
    if (!fp) {
        perror(path);
        exit(1);
    }
    fprintf(fp, "P5\n640 480\n65535\n");
    fwrite(data, 640 * 480 * 2, 1, fp);
    fclose(fp);
}

int main(int argc, char **argv) {
    const int frames = argc > 1 ? atoi(argv[1]) : 8;
    const int skip = argc > 2 ? atoi(argv[2]) : 8;
    const char *prefix = argc > 3 ? argv[3] : "registered";
    if (frames <= 0 || skip <= 0) {
        fprintf(stderr, "usage: %s [frames] [skip] [prefix]\n", argv[0]);
        return 2;
    }

    uint8_t *rgb = NULL;
    uint16_t *depth = NULL;
    uint32_t ts = 0;
    int written = 0;
    int source_index = 0;
    while (written < frames) {
        if (freenect_sync_get_video((void **)&rgb, &ts, 0, FREENECT_VIDEO_RGB) < 0) {
            fprintf(stderr, "failed to get RGB at source index %d\n", source_index);
            return 1;
        }
        if (freenect_sync_get_depth((void **)&depth, &ts, 0, FREENECT_DEPTH_REGISTERED) < 0) {
            fprintf(stderr, "failed to get registered depth at source index %d\n", source_index);
            return 1;
        }
        if (source_index % skip == 0) {
            char rgb_path[256];
            char depth_path[256];
            snprintf(rgb_path, sizeof(rgb_path), "%s_rgb_%06d.ppm", prefix, written + 1);
            snprintf(depth_path, sizeof(depth_path), "%s_depth_registered_%06d.pgm", prefix, written + 1);
            write_rgb(rgb_path, rgb);
            write_depth(depth_path, depth);
            printf("%s %s source_index=%d\n", rgb_path, depth_path, source_index);
            written++;
        }
        source_index++;
    }
    freenect_sync_stop();
    return 0;
}
