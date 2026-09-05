/* Position-independent ARM926 entry; r9 is the module GOT base inside C. */
.syntax unified
.cpu arm926ej-s
.arm
.section .entry,"ax",%progbits
.global native_entry
.type native_entry,%function
native_entry:
    push {r4-r11, lr}
    sub sp, sp, #4
    mov r4, r0
    add r5, sp, #40
    ldr r9, .Lgot_delta
.Lgot_add:
    add r9, pc, r9
    bl jpeg_probe_main
    cmn r0, #1
    beq .Lreturn
    mov r6, r0
    mrc p15, 0, r0, c0, c0, 0
    str r0, [r4, #84]
    mrc p15, 0, r0, c0, c0, 1
    str r0, [r4, #88]
    mrc p15, 0, r0, c1, c0, 0
    str r0, [r4, #92]
    mrc p15, 0, r0, c2, c0, 0
    str r0, [r4, #96]
    mrc p15, 0, r0, c3, c0, 0
    str r0, [r4, #100]
    mrs r0, cpsr
    str r0, [r4, #104]
    and r0, r5, #7
    str r0, [r4, #108]
    mov r0, r6
.Lreturn:
    add sp, sp, #4
    pop {r4-r11, pc}
.Lgot_delta:
    .word _GLOBAL_OFFSET_TABLE_ - (.Lgot_add + 8)
.size native_entry, .-native_entry
