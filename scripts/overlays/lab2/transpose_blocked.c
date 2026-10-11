#include <assert.h>
#include "dataset.h"
#include "hpm.h"

/* Only once your code passes the self-check, remove VERIFY to skip
   verification for shorter simulations */
#define VERIFY

#define min(a, b) (((a) < (b)) ? (a) : (b))

void __attribute__ ((noinline)) transpose(mat_nxm_t dst, const mat_mxn_t src)
{
    register size_t i, j, l, k;
    register size_t blocksize = 8;
    
    for (i = 0; i < MAT_M; i += blocksize) {
        for (j = 0; j < MAT_N; j += blocksize) {    
            for (l = j; l < min(j + blocksize, MAT_N); ++l) {
                for (k = i; k < min(i + blocksize, MAT_M); ++k) {
                    dst[l][k] = src[k][l];
                }
            }
        }
    }
}

int main(void)
{
    size_t i, j;

    /* Enable performance counters */
    hpm_init();

    transpose(test_dst, test_src);

    /* Print performance counter data */
    hpm_print();

#ifdef VERIFY
    /* Verify result */
    for (i = 0; i < MAT_M; i++) {
        for  (j = 0; j < MAT_N; j++) {
            assert(test_dst[j][i] == test_src[i][j]);
        }
    }
#endif

    return 0;
}
