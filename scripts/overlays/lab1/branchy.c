// Lab 1 Problem 4.1: branch-heavy program from the report (compiled -O0, rv32i).
int main(void) {
    register int x;
    for (register int i = 100; i; i--) {
        for (register int j = 100; j; j--) {
            if (i) {
                if (j) {
                    if (i) {
                        if (!j) {
                            x--;
                        } else {
                            x++;
                        }
                    }
                }
            }
        }
    }
    x = 0;
    return x;
}
