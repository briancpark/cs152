// Minimal newlib-compat stubs so the directed tests can use <assert.h> and
// fputs/stdout on top of the riscv-tests freestanding htif syscalls.c, without
// pulling in (and conflicting with) full newlib libc. See run_labs.sh / lab2.
#include <stddef.h>
#include <stdint.h>

void printstr(const char* s);   // from riscv-tests common/syscalls.c
void exit(int code);            // from riscv-tests common/syscalls.c

// stdio.h's `stdout`/`stderr` macros dereference _impure_ptr; give it a valid,
// zeroed backing buffer so the expression resolves (the stream arg is ignored).
static char _impure_buf[1024];
void* _impure_ptr = _impure_buf;

int fputs(const char* s, void* stream) { (void)stream; printstr(s); return 0; }

int puts(const char* s) { printstr(s); printstr("\n"); return 0; }

void _exit(int code) { exit(code); }

void __assert_func(const char* file, int line, const char* func, const char* expr) {
    (void)file; (void)line; (void)func;
    printstr("Assertion failed: ");
    printstr(expr);
    printstr("\n");
    exit(1);
}

// Bump allocator (libgcc emutls may reference malloc); never freed.
extern char _end[];
static char* _heap;
void* malloc(size_t n) { if (!_heap) _heap = _end; void* p = _heap; _heap += (n + 7) & ~7u; return p; }
void  free(void* p) { (void)p; }
void* calloc(size_t a, size_t b) { size_t t = a * b; char* p = malloc(t); for (size_t i = 0; i < t; i++) p[i] = 0; return p; }
void* realloc(void* p, size_t n) { (void)p; return malloc(n); }
