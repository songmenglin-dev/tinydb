package org.tinydb.jdbc.protocol;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.util.Arrays;

/**
 * Wire protocol frame: [LEN(4B BE)][TYPE(1B)][FLAGS(1B)][PAYLOAD(LEN-2 bytes)].
 * See REQ-PROTO-1 in wire-protocol spec.
 */
public final class Frame {
    public static final int MAX_FRAME_SIZE = 0xFFFFFF; // 16MB - 1

    private final int len;
    private final byte type;
    private final byte flags;
    private final byte[] payload;

    public Frame(int len, byte type, byte flags, byte[] payload) {
        this.len = len;
        this.type = type;
        this.flags = flags;
        this.payload = payload == null ? new byte[0] : payload;
    }

    public int getLen() { return len; }
    public byte getType() { return type; }
    public byte getFlags() { return flags; }
    public byte[] getPayload() { return payload; }

    /**
     * Read one frame from the stream. Returns null on clean EOF before any byte read.
     * Throws IOException on protocol errors / partial reads.
     */
    public static Frame read(DataInputStream in) throws IOException {
        int b1 = in.read();
        if (b1 == -1) {
            return null; // clean EOF
        }
        int b2 = in.read();
        int b3 = in.read();
        int b4 = in.read();
        if ((b2 | b3 | b4) == -1) {
            throw new IOException("incomplete frame header");
        }
        int len = ((b1 & 0xFF) << 24) | ((b2 & 0xFF) << 16) | ((b3 & 0xFF) << 8) | (b4 & 0xFF);
        if (len > MAX_FRAME_SIZE) {
            throw new IOException("frame too large: " + len);
        }
        byte type = in.readByte();
        byte flags = in.readByte();
        byte[] payload = new byte[len - 2];
        in.readFully(payload);
        return new Frame(len, type, flags, payload);
    }

    /**
     * Write frame to stream.
     */
    public void write(DataOutputStream out) throws IOException {
        // Verify size is consistent
        if (len != payload.length + 2) {
            throw new IOException("frame length mismatch: " + len + " != payload+2 (" + (payload.length + 2) + ")");
        }
        if (len > MAX_FRAME_SIZE) {
            throw new IOException("frame too large: " + len);
        }
        out.writeInt(len);
        out.writeByte(type);
        out.writeByte(flags);
        out.write(payload);
        out.flush();
    }

    @Override
    public String toString() {
        return "Frame{len=" + len + ", type=0x" + String.format("%02X", type & 0xFF) +
                ", flags=0x" + String.format("%02X", flags & 0xFF) +
                ", payload=" + (payload.length > 32 ? "[" + payload.length + " bytes]" : Arrays.toString(payload)) + "}";
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Frame)) return false;
        Frame f = (Frame) o;
        return len == f.len && type == f.type && flags == f.flags && Arrays.equals(payload, f.payload);
    }

    @Override
    public int hashCode() {
        return Arrays.hashCode(payload) ^ len ^ ((int)type) ^ ((int)flags);
    }
}
