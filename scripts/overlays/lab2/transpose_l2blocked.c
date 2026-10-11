#include <assert.h>
#include "dataset.h"
#include "hpm.h"

/* Only once your code passes the self-check, remove VERIFY to skip
   verification for shorter simulations */
#define VERIFY

#define min(a, b) (((a) < (b)) ? (a) : (b))

void __attribute__ ((noinline)) transpose(mat_nxm_t dst, const mat_mxn_t src)
{
    register size_t i, j, l1, k1, l2, k2;
    register size_t l1_blocksize = 8;
    register size_t l2_blocksize = 64;
    
    for (i = 0; i < MAT_M; i += l2_blocksize) {
        for (j = 0; j < MAT_N; j += l2_blocksize) {
            for (l1 = j; l1 < j + l2_blocksize; l1 += l1_blocksize) {
                for (k1 = i; k1 < i + l2_blocksize; k1 += l1_blocksize) {
                    for (l2 = l1; l2 < min(l1 + l1_blocksize, MAT_N); l2++) {
                        for (k2 = k1; k2 < min(k1 + l1_blocksize, MAT_M); k2++) {
                            dst[l2][k2] = src[k2][l2];
                        }
                    }
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
