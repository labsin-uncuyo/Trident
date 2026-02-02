# Ignore checksums for packets captured with checksum offloading
# This is necessary when capturing from network interfaces that use
# hardware checksum offloading, which results in invalid checksums
# in the captured packets.
redef ignore_checksums = T;

# Enable HTTP protocol analysis
@load base/protocols/http/main
