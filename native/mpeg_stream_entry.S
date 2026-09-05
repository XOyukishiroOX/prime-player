/* Position-independent ARM926 entry for the streaming MPEG module. */
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
    mov r10, r0
    add r5, sp, #40
    ldr r9, .Lgot_delta
.Lgot_add:
    add r9, pc, r9
    bl mpeg_stream_main
    add sp, sp, #4
    pop {r4-r11, pc}
.Lgot_delta:
    .word _GLOBAL_OFFSET_TABLE_ - (.Lgot_add + 8)
.size native_entry, .-native_entry
