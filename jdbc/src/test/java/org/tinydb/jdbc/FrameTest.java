package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.tinydb.jdbc.protocol.Frame;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

class FrameTest {

    @Test
    @DisplayName("Frame roundtrip: write then read preserves fields")
    void testRoundtrip() throws IOException {
        byte[] payload = "hello".getBytes("UTF-8");
        Frame original = new Frame(payload.length, (byte) 0x10, (byte) 0x00, payload);

        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        original.write(dos);

        DataInputStream dis = new DataInputStream(new ByteArrayInputStream(baos.toByteArray()));
        Frame decoded = Frame.read(dis);

        assertNotNull(decoded);
        assertEquals(original.getLen(), decoded.getLen());
        assertEquals(original.getType(), decoded.getType());
        assertEquals(original.getFlags(), decoded.getFlags());
        assertArrayEquals(original.getPayload(), decoded.getPayload());
    }

    @Test
    @DisplayName("Frame write produces big-endian length prefix")
    void testBigEndianLength() throws IOException {
        byte[] payload = new byte[0];
        Frame frame = new Frame(0, (byte) 0x10, (byte) 0x00, payload);

        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        frame.write(dos);

        byte[] bytes = baos.toByteArray();
        // LEN=0x00000000 (big-endian), TYPE=0x10, FLAGS=0x00
        assertEquals(6, bytes.length);
        assertEquals((byte) 0x00, bytes[0]);
        assertEquals((byte) 0x00, bytes[1]);
        assertEquals((byte) 0x00, bytes[2]);
        assertEquals((byte) 0x00, bytes[3]);
        assertEquals((byte) 0x10, bytes[4]);
        assertEquals((byte) 0x00, bytes[5]);
    }

    @Test
    @DisplayName("Frame with len=0xFFFFFF (max) roundtrips")
    void testMaxSizeFrame() throws IOException {
        int totalLen = Frame.MAX_FRAME_SIZE;
        byte[] payload = new byte[totalLen];
        payload[0] = (byte) 0xAB;
        Frame frame = new Frame(totalLen, (byte) 0x01, (byte) 0x00, payload);

        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        frame.write(dos);

        DataInputStream dis = new DataInputStream(new ByteArrayInputStream(baos.toByteArray()));
        Frame decoded = Frame.read(dis);

        assertNotNull(decoded);
        assertEquals(totalLen, decoded.getLen());
        assertEquals(payload.length, decoded.getPayload().length);
    }

    @Test
    @DisplayName("Frame with len > MAX_FRAME_SIZE throws on write")
    void testOversizeFrameWriteThrows() {
        int oversize = Frame.MAX_FRAME_SIZE + 1;
        Frame frame = new Frame(oversize, (byte) 0x01, (byte) 0x00, new byte[oversize - 2]);

        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        assertThrows(IOException.class, () -> frame.write(dos));
    }

    @Test
    @DisplayName("Frame read on empty stream returns null")
    void testReadEmptyStream() throws IOException {
        DataInputStream dis = new DataInputStream(new ByteArrayInputStream(new byte[0]));
        assertNull(Frame.read(dis));
    }

    @Test
    @DisplayName("Frame read on truncated header throws IOException")
    void testReadTruncatedHeader() throws IOException {
        // only 2 bytes when we need 6
        DataInputStream dis = new DataInputStream(new ByteArrayInputStream(new byte[]{0, 0}));
        assertThrows(IOException.class, () -> Frame.read(dis));
    }

    @Test
    @DisplayName("Frame read on truncated payload throws IOException")
    void testReadTruncatedPayload() throws IOException {
        // Header says LEN=10 but only 2 payload bytes follow
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        dos.writeInt(10); // claims 10 bytes total
        dos.writeByte(0x10);
        dos.writeByte(0x00);
        dos.write(new byte[]{1, 2}); // only 2 bytes for payload
        DataInputStream dis = new DataInputStream(new ByteArrayInputStream(baos.toByteArray()));
        assertThrows(IOException.class, () -> Frame.read(dis));
    }

    @Test
    @DisplayName("Frame equals and hashCode work")
    void testEqualsHashCode() {
        Frame a = new Frame(5, (byte) 0x10, (byte) 0x00, "hello".getBytes());
        Frame b = new Frame(5, (byte) 0x10, (byte) 0x00, "hello".getBytes());
        Frame c = new Frame(5, (byte) 0x10, (byte) 0x00, "world".getBytes());
        assertEquals(a, b);
        assertEquals(a.hashCode(), b.hashCode());
        assertEquals(false, a.equals(c));
    }
}
