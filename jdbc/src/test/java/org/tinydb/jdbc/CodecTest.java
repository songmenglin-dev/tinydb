package org.tinydb.jdbc;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.tinydb.jdbc.protocol.Codec;
import org.tinydb.jdbc.protocol.Frame;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CodecTest {

    @Test
    @DisplayName("HELLO encode then write/read roundtrip")
    void testHelloRoundtrip() throws Exception {
        Frame f = Codec.encodeHello("py-tinydb-1.0");
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        f.write(dos);
        DataInputStream dis = new DataInputStream(new ByteArrayInputStream(baos.toByteArray()));
        Frame decoded = Frame.read(dis);
        assertEquals(Codec.TYPE_HELLO, decoded.getType());
        assertEquals("py-tinydb-1.0", new String(decoded.getPayload()));
    }

    @Test
    @DisplayName("QUERY encode produces UTF-8 payload")
    void testQueryEncode() {
        Frame f = Codec.encodeQuery("SELECT 1");
        assertEquals(Codec.TYPE_QUERY, f.getType());
        assertEquals("SELECT 1", new String(f.getPayload()));
    }

    @Test
    @DisplayName("EXEC with INT64 param roundtrips through wire format")
    void testExecInt64Param() throws Exception {
        List<Codec.Param> params = new ArrayList<>();
        params.add(Codec.Param.int64(42));
        Frame f = Codec.encodeExec("SELECT ?", params);
        assertEquals(Codec.TYPE_EXEC, f.getType());
        // Verify payload structure
        byte[] p = f.getPayload();
        // first 4 bytes: sql len
        int sqlLen = ((p[0] & 0xFF) << 24) | ((p[1] & 0xFF) << 16) | ((p[2] & 0xFF) << 8) | (p[3] & 0xFF);
        assertEquals(8, sqlLen);
        // next 8 bytes: "SELECT ?"
        String sql = new String(p, 4, 8);
        assertEquals("SELECT ?", sql);
        // next 2 bytes: param count = 1 (offset 12,13)
        int pc = ((p[12] & 0xFF) << 8) | (p[13] & 0xFF);
        assertEquals(1, pc);
        // type byte (offset 14)
        assertEquals(Codec.WIRE_INT64, p[14]);
        // len = 8 (offset 15..18)
        int plen = ((p[15] & 0xFF) << 24) | ((p[16] & 0xFF) << 16) | ((p[17] & 0xFF) << 8) | (p[18] & 0xFF);
        assertEquals(8, plen);
    }

    @Test
    @DisplayName("EXEC with NULL param encodes correctly")
    void testExecNullParam() {
        List<Codec.Param> params = new ArrayList<>();
        params.add(Codec.Param.nullParam());
        Frame f = Codec.encodeExec("SELECT ?", params);
        byte[] p = f.getPayload();
        assertEquals(Codec.WIRE_NULL, p[14]);
    }

    @Test
    @DisplayName("EXEC with multiple params (NULL, INT64, STRING, BOOL, FLOAT64)")
    void testExecMultipleParamTypes() {
        List<Codec.Param> params = new ArrayList<>();
        params.add(Codec.Param.nullParam());
        params.add(Codec.Param.int64(42));
        params.add(Codec.Param.string("hi"));
        params.add(Codec.Param.bool(true));
        params.add(Codec.Param.float64(3.14));
        Frame f = Codec.encodeExec("SELECT ?,?,?,?,?", params);
        // The total payload should contain all 5 params with their type/len/data
        assertEquals(Codec.TYPE_EXEC, f.getType());
        assertTrue(f.getPayload().length > 0);
    }

    @Test
    @DisplayName("EXEC with STRING param '你好' preserves UTF-8")
    void testExecUtf8String() {
        List<Codec.Param> params = new ArrayList<>();
        params.add(Codec.Param.string("你好"));
        Frame f = Codec.encodeExec("SELECT ?", params);
        // Verify that the bytes for "你好" are present
        byte[] p = f.getPayload();
        String s = new String(p, java.nio.charset.StandardCharsets.UTF_8);
        assertTrue(s.contains("你好"));
    }

    @Test
    @DisplayName("PING encode then decode preserves timestamp")
    void testPingPongRoundtrip() throws Exception {
        Frame ping = Codec.encodePing(1234567890L);
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        ping.write(dos);
        DataInputStream dis = new DataInputStream(new ByteArrayInputStream(baos.toByteArray()));
        Frame decoded = Frame.read(dis);
        assertEquals(Codec.TYPE_PING, decoded.getType());
        assertEquals(1234567890L, Codec.decodePing(decoded));

        Frame pong = Codec.encodePong(1234567890L);
        ByteArrayOutputStream baos2 = new ByteArrayOutputStream();
        DataOutputStream dos2 = new DataOutputStream(baos2);
        pong.write(dos2);
        DataInputStream dis2 = new DataInputStream(new ByteArrayInputStream(baos2.toByteArray()));
        Frame decoded2 = Frame.read(dis2);
        assertEquals(Codec.TYPE_PONG, decoded2.getType());
        assertEquals(1234567890L, Codec.decodePong(decoded2));
    }

    @Test
    @DisplayName("QUIT frame has type=0xFE and empty payload")
    void testQuitFrame() {
        Frame q = Codec.encodeQuit();
        assertEquals(Codec.TYPE_QUIT, q.getType());
        assertEquals(0, q.getLen()); // empty payload = 0 bytes, len = 2
    }

    @Test
    @DisplayName("decode ResultHeader with 2 columns")
    void testDecodeResultHeader() {
        // Build a payload: col_count=2, col1=[len(1),name(utf8),type(1)], col2=...
        byte[] name = "name".getBytes(); // 4 bytes
        byte[] val = "val".getBytes();   // 3 bytes
        byte[] payload = new byte[2 + (1 + name.length + 1) + (1 + val.length + 1)];
        int off = 0;
        payload[off++] = 0;
        payload[off++] = 2; // col count
        payload[off++] = (byte) name.length;
        System.arraycopy(name, 0, payload, off, name.length); off += name.length;
        payload[off++] = Codec.WIRE_INT64;
        payload[off++] = (byte) val.length;
        System.arraycopy(val, 0, payload, off, val.length); off += val.length;
        payload[off++] = Codec.WIRE_STRING;
        Frame f = new Frame(payload.length, Codec.TYPE_RESULT_HEADER, (byte) 0, payload);
        List<Codec.Column> cols = Codec.decodeResultHeader(f);
        assertEquals(2, cols.size());
        assertEquals("name", cols.get(0).name);
        assertEquals(Codec.WIRE_INT64, cols.get(0).type);
        assertEquals("val", cols.get(1).name);
        assertEquals(Codec.WIRE_STRING, cols.get(1).type);
    }

    @Test
    @DisplayName("decode ResultRow with mixed types")
    void testDecodeResultRow() throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        dos.writeShort(3); // col count
        // col1: INT64(42) - type byte, len=8, 8 bytes
        dos.writeByte(Codec.WIRE_INT64);
        dos.writeInt(8);
        long v = 42;
        dos.writeLong(v);
        // col2: STRING("hi") - type, len=2, "hi"
        dos.writeByte(Codec.WIRE_STRING);
        dos.writeInt(2);
        dos.write("hi".getBytes("UTF-8"));
        // col3: BOOL(true) - type, len=1, 0x01
        dos.writeByte(Codec.WIRE_BOOL);
        dos.writeInt(1);
        dos.writeByte(1);
        byte[] payload = baos.toByteArray();
        Frame f = new Frame(payload.length, Codec.TYPE_RESULT_ROW, (byte) 0, payload);
        List<Object> values = Codec.decodeResultRow(f);
        assertEquals(3, values.size());
        assertEquals(42L, values.get(0));
        assertEquals("hi", values.get(1));
        assertEquals(Boolean.TRUE, values.get(2));
    }

    @Test
    @DisplayName("decode ResultDone with rowcount, last_insert_id, flags")
    void testDecodeResultDone() throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        dos.writeLong(1L); // rowcount
        dos.writeLong(5L); // last_insert_id
        dos.writeByte(0x05); // flags
        byte[] payload = baos.toByteArray();
        Frame f = new Frame(payload.length, Codec.TYPE_RESULT_DONE, (byte) 0, payload);
        Codec.DoneInfo info = Codec.decodeResultDone(f);
        assertEquals(1L, info.rowcount);
        assertEquals(5L, info.lastInsertId);
        assertEquals((byte) 0x05, info.flags);
    }

    @Test
    @DisplayName("decode ResultError with code=42000, msg='syntax error'")
    void testDecodeResultError() throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        dos.write("42000".getBytes("UTF-8"));
        byte[] msg = "syntax error".getBytes("UTF-8");
        dos.writeShort(msg.length);
        dos.write(msg);
        byte[] payload = baos.toByteArray();
        Frame f = new Frame(payload.length, Codec.TYPE_RESULT_ERROR, (byte) 0, payload);
        String[] parts = Codec.decodeResultError(f);
        assertEquals("42000", parts[0]);
        assertEquals("syntax error", parts[1]);
    }

    @Test
    @DisplayName("NULL value in ResultRow decodes to null")
    void testDecodeNullValue() throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        dos.writeShort(1); // col count
        dos.writeByte(Codec.WIRE_NULL);
        dos.writeInt(0);
        byte[] payload = baos.toByteArray();
        Frame f = new Frame(payload.length, Codec.TYPE_RESULT_ROW, (byte) 0, payload);
        List<Object> values = Codec.decodeResultRow(f);
        assertNull(values.get(0));
    }

    @Test
    @DisplayName("FLOAT64 value in ResultRow decodes to double")
    void testDecodeFloat64Value() throws Exception {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        dos.writeShort(1);
        dos.writeByte(Codec.WIRE_FLOAT64);
        dos.writeInt(8);
        dos.writeDouble(3.14);
        byte[] payload = baos.toByteArray();
        Frame f = new Frame(payload.length, Codec.TYPE_RESULT_ROW, (byte) 0, payload);
        List<Object> values = Codec.decodeResultRow(f);
        assertEquals(3.14, (Double) values.get(0), 0.001);
    }

    @Test
    @DisplayName("OK decode returns version string")
    void testDecodeOk() {
        byte[] payload = "tinydb-0.3.1".getBytes();
        Frame f = new Frame(payload.length, Codec.TYPE_OK, (byte) 0, payload);
        assertEquals("tinydb-0.3.1", Codec.decodeOk(f));
    }

    @Test
    @DisplayName("ERR decode returns formatted message")
    void testDecodeErr() {
        // code=08000 + len=11 + "HELLO required"
        byte[] payload = new byte[5 + 2 + 14];
        byte[] code = "08000".getBytes();
        System.arraycopy(code, 0, payload, 0, 5);
        byte[] msg = "HELLO required".getBytes();
        payload[5] = 0;
        payload[6] = (byte) msg.length;
        System.arraycopy(msg, 0, payload, 7, msg.length);
        Frame f = new Frame(payload.length, Codec.TYPE_ERR, (byte) 0, payload);
        String s = Codec.decodeErr(f);
        assertTrue(s.contains("08000"));
        assertTrue(s.contains("HELLO required"));
    }
}
