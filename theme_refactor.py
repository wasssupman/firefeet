import re

with open('web/frontend/src/app/page.tsx', 'r') as f:
    text = f.read()

# Replace hardcoded dark mode colors with Next-Theme semantic colors
replacements = {
    r'\bbg-black\b': 'bg-background',
    r'\bbg-\[\#0a0a0a\]\b': 'bg-muted/30',
    r'\bbg-zinc-950\b': 'bg-card',
    r'\bbg-zinc-900/50\b': 'bg-muted/50 hover:bg-muted',
    r'\bbg-zinc-900\b': 'bg-muted',
    r'\bborder-zinc-800\b': 'border-border',
    r'\bborder-zinc-900\b': 'border-border/40',
    r'\btext-zinc-100\b': 'text-foreground',
    r'\btext-zinc-300\b': 'text-foreground/80',
    r'\btext-zinc-400\b': 'text-muted-foreground',
    r'\btext-zinc-500\b': 'text-muted-foreground',
    r'\btext-zinc-600\b': 'text-muted-foreground/70',
}

for pattern, repl in replacements.items():
    text = re.sub(pattern, repl, text)

# Insert ThemeToggle import
if "import { ThemeToggle }" not in text:
    text = text.replace('import { Badge } from "@/components/ui/badge";', 'import { Badge } from "@/components/ui/badge";\nimport { ThemeToggle } from "@/components/theme-toggle";')

# Insert ThemeToggle button next to "Uplink Active" badge
if "<ThemeToggle />" not in text:
    target = 'Uplink Active\n                </>\n              ) : "Connecting..."}\n            </Badge>'
    replacement = target + '\n            <ThemeToggle />'
    text = text.replace(target, replacement)

with open('web/frontend/src/app/page.tsx', 'w') as f:
    f.write(text)

print("Refactor complete!")
