package org.tinydb.jdbc.protocol;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * Wire protocol message encode/decode for all 12 message types.
 * Wire protocol types:
 *  0x01 HELLO       C->S  client_id(utf8)
 *  0x02 OK          S->C  version(utf8)
 *  0x03 ERR         S->C  code(5 ASCII), msg_len(2 BE), msg(utf8)
 *  0x10 QUERY       C->S  sql(utf8)
 *  0x11 EXEC        C->S  sql_len(4 BE), sql(utf8), param_count(2 BE), params[...]
 *  0x20 RESULT_HEADER S->C  col_count(2 BE), cols[name_len(1), name(utf8), type(1)]
 *  0x21 RESULT_ROW  S->C  col_count(2 BE), values[type(1), len(4 BE), data]
 *  0x22 RESULT_DONE S->C  rowcount(8 BE), last_insert_id(8 BE), status_flags(1)
 *  0x23 RESULT_ERROR S->C code(5 ASCII), msg_len(2 BE), msg(utf8)
 *  0x30 PING        C<->S ts(8 BE)
 *  0x31 PONG        C<->S ts(8 BE)
 *  0xFE QUIT        C->S  empty
 */
public final class Codec {
    public static final byte TYPE_HELLO = 0x01;
    public static final byte TYPE_OK = 0x02;
    public static final byte TYPE_ERR = 0x03;
    public static final byte TYPE_QUERY = 0x10;
    public static final byte TYPE_EXEC = 0x11;
    public static final byte TYPE_RESULT_HEADER = 0x20;
    public static final byte TYPE_RESULT_ROW = 0x21;
    public static final byte TYPE_RESULT_DONE = 0x22;
    public static final byte TYPE_RESULT_ERROR = 0x23;
    public static final byte TYPE_PING = 0x30;
    public static final byte TYPE_PONG = 0x31;
    public static final byte TYPE_QUIT = (byte) 0xFE;

    // Parameter type codes
    public static final byte WIRE_NULL = 0x00;
    public static final byte WIRE_INT64 = 0x01;
    public static final byte WIRE_FLOAT64 = 0x02;
    public static final byte WIRE_STRING = 0x03;
    public static final byte WIRE_BOOL = 0x04;

    // Status flags for RESULT_DONE
    public static final byte FLAG_AUTOCOMMIT = 0x01;
    public static final byte FLAG_IN_TRANSACTION = 0x02;
    public static final byte FLAG_NO_RESULT = 0x04;

    private Codec() {}

    // ===== C->S encoders =====

    public static Frame encodeHello(String clientId) {
        byte[] data = clientId.getBytes(StandardCharsets.UTF_8);
        return makeFrame(TYPE_HELLO, data);
    }

    public static Frame encodeQuery(String sql) {
        byte[] data = sql.getBytes(StandardCharsets.UTF_8);
        return makeFrame(TYPE_QUERY, data);
    }

    public static Frame encodeExec(String sql, List<Param> params) {
        if (params == null) params = new ArrayList<>();
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        try {
            byte[] sqlBytes = sql.getBytes(StandardCharsets.UTF_8);
            dos.writeInt(sqlBytes.length);
            dos.write(sqlBytes);
            if (params.size() > 0xFFFF) {
                throw new IOException("too many params: " + params.size());
            }
            dos.writeShort(params.size());
            for (Param p : params) {
                dos.writeByte(p.type & 0xFF);
                byte[] valBytes = p.encodeValue();
                dos.writeInt(valBytes.length);
                dos.write(valBytes);
            }
        } catch (IOException e) {
            throw new RuntimeException("encodeExec failed", e);
        }
        return makeFrame(TYPE_EXEC, baos.toByteArray());
    }

    public static Frame encodePing(long ts) {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        try {
            dos.writeLong(ts);
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
        return makeFrame(TYPE_PING, baos.toByteArray());
    }

    public static Frame encodePong(long ts) {
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DataOutputStream dos = new DataOutputStream(baos);
        try {
            dos.writeLong(ts);
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
        return makeFrame(TYPE_PONG, baos.toByteArray());
    }

    public static Frame encodeQuit() {
        return makeFrame(TYPE_QUIT, new byte[0]);
    }

    // ===== S->C decoders =====

    public static String decodeOk(Frame frame) {
        return new String(frame.getPayload(), StandardCharsets.UTF_8);
    }

    public static String decodeErr(Frame frame) {
        return decodeErrorPayload(frame.getPayload());
    }

    public static String[] decodeResultError(Frame frame) {
        String[] r = decodeErrorPayloadParts(frame.getPayload());
        return new String[]{r[0], r[1]};
    }

    public static List<Column> decodeResultHeader(Frame frame) {
        byte[] payload = frame.getPayload();
        if (payload.length < 2) {
            throw new IllegalArgumentException("RESULT_HEADER payload too short: " + payload.length);
        }
        int colCount = ((payload[0] & 0xFF) << 8) | (payload[1] & 0xFF);
        List<Column> cols = new ArrayList<>(colCount);
        int off = 2;
        for (int i = 0; i < colCount; i++) {
            if (off + 2 > payload.length) {
                throw new IllegalArgumentException("RESULT_HEADER truncated at column " + i);
            }
            int nameLen = payload[off] & 0xFF;
            off++;
            if (off + nameLen + 1 > payload.length) {
                throw new IllegalArgumentException("RESULT_HEADER name overruns payload at column " + i);
            }
            String name = new String(payload, off, nameLen, StandardCharsets.UTF_8);
            off += nameLen;
            byte type = payload[off];
            off++;
            cols.add(new Column(name, type));
        }
        return cols;
    }

    public static List<Object> decodeResultRow(Frame frame) {
        byte[] payload = frame.getPayload();
        if (payload.length < 2) {
            throw new IllegalArgumentException("RESULT_ROW payload too short: " + payload.length);
        }
        int colCount = ((payload[0] & 0xFF) << 8) | (payload[1] & 0xFF);
        List<Object> values = new ArrayList<>(colCount);
        int off = 2;
        for (int i = 0; i < colCount; i++) {
            if (off + 5 > payload.length) {
                throw new IllegalArgumentException("RESULT_ROW truncated at value " + i);
            }
            byte type = payload[off];
            off++;
            int len = ((payload[off] & 0xFF) << 24) | ((payload[off+1] & 0xFF) << 16) |
                      ((payload[off+2] & 0xFF) << 8) | (payload[off+3] & 0xFF);
            off += 4;
            if (off + len > payload.length) {
                throw new IllegalArgumentException("RESULT_ROW value data overruns payload at value " + i);
            }
            byte[] data = new byte[len];
            System.arraycopy(payload, off, data, 0, len);
            off += len;
            values.add(decodeValue(type, data));
        }
        return values;
    }

    public static DoneInfo decodeResultDone(Frame frame) {
        byte[] payload = frame.getPayload();
        if (payload.length < 17) {
            throw new IllegalArgumentException("RESULT_DONE payload too short: " + payload.length);
        }
        long rowcount = readLongBE(payload, 0);
        long lastInsertId = readLongBE(payload, 8);
        byte flags = payload[16];
        return new DoneInfo(rowcount, lastInsertId, flags);
    }

    public static long decodePing(Frame frame) {
        byte[] payload = frame.getPayload();
        if (payload.length < 8) {
            throw new IllegalArgumentException("PING payload too short: " + payload.length);
        }
        return readLongBE(payload, 0);
    }

    public static long decodePong(Frame frame) {
        byte[] payload = frame.getPayload();
        if (payload.length < 8) {
            throw new IllegalArgumentException("PONG payload too short: " + payload.length);
        }
        return readLongBE(payload, 0);
    }

    // ===== Helpers =====

    private static Frame makeFrame(byte type, byte[] data) {
        return new Frame(data.length + 2, type, (byte) 0x00, data);
    }

    private static long readLongBE(byte[] b, int off) {
        return ((long)(b[off] & 0xFF) << 56) | ((long)(b[off+1] & 0xFF) << 48) |
               ((long)(b[off+2] & 0xFF) << 40) | ((long)(b[off+3] & 0xFF) << 32) |
               ((long)(b[off+4] & 0xFF) << 24) | ((long)(b[off+5] & 0xFF) << 16) |
               ((long)(b[off+6] & 0xFF) << 8)  | ((long)(b[off+7] & 0xFF));
    }

    private static String[] decodeErrorPayloadParts(byte[] payload) {
        if (payload.length < 7) {
            throw new IllegalArgumentException("ERR payload too short: " + payload.length);
        }
        String code = new String(payload, 0, 5, StandardCharsets.UTF_8);
        int msgLen = ((payload[5] & 0xFF) << 8) | (payload[6] & 0xFF);
        if (7 + msgLen > payload.length) {
            throw new IllegalArgumentException("ERR msg overruns payload: len=" + msgLen + ", avail=" + (payload.length - 7));
        }
        String msg = new String(payload, 7, msgLen, StandardCharsets.UTF_8);
        return new String[]{code, msg};
    }

    private static String decodeErrorPayload(byte[] payload) {
        String[] parts = decodeErrorPayloadParts(payload);
        return parts[0] + ": " + parts[1];
    }

    private static Object decodeValue(byte type, byte[] data) {
        switch (type) {
            case WIRE_NULL:
                return null;
            case WIRE_INT64: {
                if (data.length < 8) {
                    throw new IllegalArgumentException("INT64 data too short: " + data.length);
                }
                long v = ((long)(data[0] & 0xFF) << 56) | ((long)(data[1] & 0xFF) << 48) |
                          ((long)(data[2] & 0xFF) << 40) | ((long)(data[3] & 0xFF) << 32) |
                          ((long)(data[4] & 0xFF) << 24) | ((long)(data[5] & 0xFF) << 16) |
                          ((long)(data[6] & 0xFF) << 8)  | ((long)(data[7] & 0xFF));
                return v;
            }
            case WIRE_FLOAT64: {
                if (data.length < 8) {
                    throw new IllegalArgumentException("FLOAT64 data too short: " + data.length);
                }
                long bits = ((long)(data[0] & 0xFF) << 56) | ((long)(data[1] & 0xFF) << 48) |
                            ((long)(data[2] & 0xFF) << 40) | ((long)(data[3] & 0xFF) << 32) |
                            ((long)(data[4] & 0xFF) << 24) | ((long)(data[5] & 0xFF) << 16) |
                            ((long)(data[6] & 0xFF) << 8)  | ((long)(data[7] & 0xFF));
                return Double.longBitsToDouble(bits);
            }
            case WIRE_STRING:
                return new String(data, StandardCharsets.UTF_8);
            case WIRE_BOOL: {
                if (data.length < 1) {
                    throw new IllegalArgumentException("BOOL data too short: " + data.length);
                }
                return data[0] != 0;
            }
            default:
                throw new IllegalArgumentException("unknown wire type: 0x" + String.format("%02X", type & 0xFF));
        }
    }

    // ===== Inner types =====

    public static final class Column {
        public final String name;
        public final byte type;

        public Column(String name, byte type) {
            this.name = name;
            this.type = type;
        }

        @Override
        public String toString() {
            return "Column{name='" + name + "', type=0x" + String.format("%02X", type & 0xFF) + "}";
        }
    }

    public static final class DoneInfo {
        public final long rowcount;
        public final long lastInsertId;
        public final byte flags;

        public DoneInfo(long rowcount, long lastInsertId, byte flags) {
            this.rowcount = rowcount;
            this.lastInsertId = lastInsertId;
            this.flags = flags;
        }

        @Override
        public String toString() {
            return "DoneInfo{rowcount=" + rowcount + ", lastInsertId=" + lastInsertId +
                    ", flags=0x" + String.format("%02X", flags & 0xFF) + "}";
        }
    }

    public static final class Param {
        public final byte type;
        public final Object value;

        public Param(byte type, Object value) {
            this.type = type;
            this.value = value;
        }

        public byte[] encodeValue() {
            switch (type) {
                case WIRE_NULL: return new byte[0];
                case WIRE_INT64: {
                    long v = ((Number) value).longValue();
                    return new byte[]{
                        (byte)(v >>> 56), (byte)(v >>> 48), (byte)(v >>> 40), (byte)(v >>> 32),
                        (byte)(v >>> 24), (byte)(v >>> 16), (byte)(v >>> 8),  (byte)(v)
                    };
                }
                case WIRE_FLOAT64: {
                    long bits = Double.doubleToRawLongBits(((Number) value).doubleValue());
                    return new byte[]{
                        (byte)(bits >>> 56), (byte)(bits >>> 48), (byte)(bits >>> 40), (byte)(bits >>> 32),
                        (byte)(bits >>> 24), (byte)(bits >>> 16), (byte)(bits >>> 8),  (byte)(bits)
                    };
                }
                case WIRE_STRING: {
                    return ((String) value).getBytes(StandardCharsets.UTF_8);
                }
                case WIRE_BOOL: {
                    return new byte[]{((Boolean) value).booleanValue() ? (byte) 1 : (byte) 0};
                }
                default:
                    throw new IllegalArgumentException("unknown wire type: 0x" + String.format("%02X", type & 0xFF));
            }
        }

        public static Param nullParam() { return new Param(WIRE_NULL, null); }
        public static Param int64(long v) { return new Param(WIRE_INT64, v); }
        public static Param float64(double v) { return new Param(WIRE_FLOAT64, v); }
        public static Param string(String s) { return new Param(WIRE_STRING, s); }
        public static Param bool(boolean b) { return new Param(WIRE_BOOL, b); }
    }
}
