.global _start

.section .text
_start:
    # Read the fixed smoke-test input.
    mov $257, %rax
    mov $-100, %rdi
    lea input_path(%rip), %rsi
    xor %rdx, %rdx
    xor %r10, %r10
    syscall
    test %rax, %rax
    js fail_input
    mov %rax, %r12

    xor %rax, %rax
    mov %r12, %rdi
    lea buffer(%rip), %rsi
    mov $4096, %rdx
    syscall
    test %rax, %rax
    js fail_input
    mov %rax, %r13

    # Create the fixed smoke-test artifact.
    mov $257, %rax
    mov $-100, %rdi
    lea output_path(%rip), %rsi
    mov $577, %rdx
    mov $420, %r10
    syscall
    test %rax, %rax
    js fail_output
    mov %rax, %r14

    mov $1, %rax
    mov %r14, %rdi
    lea prefix(%rip), %rsi
    mov $prefix_len, %rdx
    syscall

    mov $1, %rax
    mov %r14, %rdi
    lea buffer(%rip), %rsi
    mov %r13, %rdx
    syscall

    mov $1, %rax
    mov $1, %rdi
    lea success(%rip), %rsi
    mov $success_len, %rdx
    syscall

    xor %rdi, %rdi
    jmp exit

fail_input:
    mov $10, %rdi
    jmp exit

fail_output:
    mov $11, %rdi

exit:
    mov $60, %rax
    syscall

.section .rodata
input_path:
    .asciz "/workspace/inputs/container-smoke.txt"
output_path:
    .asciz "/workspace/outputs/container-smoke.txt"
prefix:
    .ascii "isolated:"
.equ prefix_len, . - prefix
success:
    .ascii "container-smoke-ok\n"
.equ success_len, . - success

.section .bss
.align 16
buffer:
    .skip 4096
