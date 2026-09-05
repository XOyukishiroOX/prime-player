OUTPUT_FORMAT("elf32-littlearm")
OUTPUT_ARCH(arm)
ENTRY(native_entry)
SECTIONS {
    . = 0;
    .entry : { KEEP(*(.entry)) }
    .text : { *(.text*) }
    .rodata : { *(.rodata*) *(.data.rel.ro*) }
    .got ALIGN(4) : { *(.got*) }
    .module_pad : { BYTE(0); . = ALIGN(32); }
    .data ALIGN(4) : { *(.data*) }
    .bss ALIGN(4) : { *(.bss*) *(COMMON) }
    .module_end_pad : { . = ALIGN(32); }
    __module_end = .;
    /DISCARD/ : { *(.comment) *(.note*) *(.ARM.attributes) *(.eh_frame*) }
}
ASSERT(SIZEOF(.bss) == 0, "Unexpected uninitialized data")
ASSERT((__module_end % 32) == 0, "Module must end on a cache line")
