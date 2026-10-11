/* rv32i (Sodor) has no A extension; single-core so a plain RMW is fine. */
unsigned int __sync_fetch_and_add_4(volatile void *p, unsigned int v)
{
    volatile unsigned int *q = p;
    unsigned int old = *q;
    *q = old + v;
    return old;
}
