# Installation Guide

## Prerequisites

### System Requirements

- Linux kernel 4.9+ with eBPF support
- Python 3.10 or higher
- Root/sudo access (required for eBPF)
- PostgreSQL 14, 15, 16, 17, or 18 with debug symbols

### Installing BCC (BPF Compiler Collection)

#### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install bpfcc-tools linux-headers-$(uname -r) python3-bpfcc
```

#### RHEL/CentOS/Fedora

```bash
sudo dnf install bcc-tools python3-bcc kernel-devel
```

#### Arch Linux

```bash
sudo pacman -S bcc bcc-tools python-bcc
```

### Installing PostgreSQL with Debug Symbols

Debug symbols are required for the tool to locate the `add_path` and `create_plan` functions.

#### Ubuntu/Debian

```bash
# Install PostgreSQL and debug symbols
sudo apt-get install postgresql-16 postgresql-16-dbgsym

# If dbgsym is not available, enable debug symbol repository:
echo "deb http://ddebs.ubuntu.com $(lsb_release -cs) main restricted universe multiverse" | \
  sudo tee -a /etc/apt/sources.list.d/ddebs.list
sudo apt-get update
sudo apt-get install postgresql-16-dbgsym
```

#### Building PostgreSQL from Source with Debug Symbols

```bash
# Download PostgreSQL source
wget https://ftp.postgresql.org/pub/source/v16.1/postgresql-16.1.tar.gz
tar xzf postgresql-16.1.tar.gz
cd postgresql-16.1

# Configure with debug symbols
./configure --enable-debug --enable-cassert --prefix=/usr/local/pgsql

# Build and install
make
sudo make install
```

## Installing pg_plan_alternatives

### From PyPI (when published)

```bash
pip install pg_plan_alternatives
```

### From Source

```bash
# Clone the repository
git clone https://github.com/jnidzwetzki/pg_plan_alternatives.git
cd pg_plan_alternatives

# Install in development mode
pip install -e .

# Or build and install
pip install build
python -m build
pip install dist/pg_plan_alternatives-*.whl
```

### Installing Dependencies

```bash
# Install graphviz for visualization
sudo apt-get install graphviz  # Ubuntu/Debian
# or
sudo dnf install graphviz      # RHEL/CentOS/Fedora

# Install Python package
pip install graphviz
```

## Verifying Installation

1. Check if pg_plan_alternatives is installed:

```bash
pg_plan_alternatives --version
```

2. Check if PostgreSQL binary has debug symbols:

```bash
# Find your PostgreSQL binary
which postgres
# or
ps aux | grep postgres | head -1

# Check for symbols (should show add_path)
nm /usr/lib/postgresql/16/bin/postgres | grep add_path
```

If you don't see `add_path`, you need to install PostgreSQL with debug symbols.

3. Check if BPF is working:

```bash
# Check if BPF filesystem is mounted
mount | grep bpf

# Test BPF with a simple tool
sudo bpftrace -e 'BEGIN { printf("BPF is working!\n"); exit(); }'
```

## Troubleshooting

### "Error: This tool requires root privileges"

The tool needs root access to use eBPF. Run with sudo:

```bash
sudo pg_plan_alternatives -x /path/to/postgres -p <PID>
```

### "Error: Binary not found"

Make sure to provide the full path to the PostgreSQL binary:

```bash
# Find the binary path
ps aux | grep postgres
# Look for something like /usr/lib/postgresql/16/bin/postgres

# Use that path
sudo pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres
```

### "Error attaching uprobes"

This usually means:
1. The binary doesn't have debug symbols
2. The function names have changed in your PostgreSQL version
3. The binary path is incorrect

Verify with:

```bash
nm /path/to/postgres | grep -E "add_path|create_plan"
```

### "No module named 'bcc'"

BCC is not installed or not in Python path:

```bash
# Ubuntu/Debian
sudo apt-get install python3-bpfcc

# RHEL/CentOS/Fedora  
sudo dnf install python3-bcc
```

## Next Steps

After installation, see the [examples](examples/README.md) directory for usage examples.
