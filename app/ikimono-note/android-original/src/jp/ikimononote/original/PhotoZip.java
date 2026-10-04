package jp.ikimononote.original;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import java.util.zip.CRC32;

/** Wraps the original bytes without decoding or re-encoding the photograph. */
public final class PhotoZip {
    public static final int LIMIT = 15 * 1024 * 1024;

    public static String safeName(String name) {
        if (name == null || name.isEmpty() || name.length() > 200 || name.contains("/")
                || name.contains("\\") || name.equals(".") || name.equals("..")
                || name.indexOf('\0') >= 0) return "photo.jpg";
        return name;
    }

    private static byte[] wrap(byte[] photo, String name) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            ZipEntry entry = new ZipEntry(safeName(name));
            // STORED has no variable compression size or trailing data descriptor.
            entry.setMethod(ZipEntry.STORED);
            entry.setSize(photo.length);
            CRC32 crc = new CRC32();
            crc.update(photo);
            entry.setCrc(crc.getValue());
            entry.setTime(315619200000L); // 1980-01-02 UTC; no extended timestamp field.
            zip.putNextEntry(entry);
            zip.write(photo);
            zip.closeEntry();
        }
        return output.toByteArray();
    }

    public static long size(long photoSize, String name) throws IOException {
        return photoSize + wrap(new byte[0], name).length;
    }

    public static byte[] create(InputStream original, String name) throws IOException {
        ByteArrayOutputStream photo = new ByteArrayOutputStream();
        byte[] buffer = new byte[32 * 1024];
        int total = 0, count;
        while ((count = original.read(buffer)) != -1) {
            total += count;
            if (total > LIMIT) throw new IOException("写真は15MB以下にしてください。");
            photo.write(buffer, 0, count);
        }
        if (total == 0) throw new IOException("写真を読み取れませんでした。");
        if (size(total, name) > LIMIT) throw new IOException("ZIPは15MB以下にしてください。");
        byte[] output = wrap(photo.toByteArray(), name);
        if (output.length > LIMIT) throw new IOException("ZIPは15MB以下にしてください。");
        return output;
    }

    private PhotoZip() {}
}
