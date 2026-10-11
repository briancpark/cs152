/* Lab 5 lab/common/util.c with the barrier's __thread sense flag replaced by a
 * per-hart array. The local xPack toolchain is built with --disable-tls, so
 * __thread lowers to emulated TLS, which is a single shared copy on bare metal
 * and deadlocks the barrier. Behaviour is otherwise identical. */
#include "util.h"

#define MAX_HARTS 8

int barrier(void)
{
    static volatile int sense;
    static volatile int count = 0;
    static int threadsense[MAX_HARTS];
    const unsigned long hart = read_csr(mhartid);
    int rc;

    __sync_synchronize();
    threadsense[hart] = !threadsense[hart];
    if (__sync_fetch_and_add(&count, 1) == nharts-1) {
        count = 0;
        sense = threadsense[hart];
	rc = 1;
    } else {
        while (sense != threadsense[hart]);
	rc = 0;
    }
    __sync_synchronize();
    return rc;
}
