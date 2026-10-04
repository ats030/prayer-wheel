import jp.ikimononote.original.PhotoZip;
import java.io.*;
import java.nio.file.*;
import java.util.Arrays;
import java.util.zip.*;

public class PhotoZipTest {
    static void check(boolean condition) { if (!condition) throw new AssertionError(); }
    static void rejects(InputStream input) throws Exception {
        try { PhotoZip.create(input, "photo.jpg"); throw new AssertionError("accepted invalid input"); }
        catch (IOException expected) {}
    }
    public static void main(String[] args) throws Exception {
        byte[] original = Files.readAllBytes(Paths.get(args[0]));
        String name = PhotoZip.safeName(Paths.get(args[0]).getFileName().toString());
        byte[] zip = PhotoZip.create(new ByteArrayInputStream(original), name);
        check(zip.length == PhotoZip.size(original.length, name));
        try (ZipInputStream input = new ZipInputStream(new ByteArrayInputStream(zip))) {
            check(input.getNextEntry().getName().equals(name));
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192]; int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
            check(Arrays.equals(original, output.toByteArray()));
            check(input.getNextEntry() == null);
        }
        rejects(new ByteArrayInputStream(new byte[0]));
        rejects(new ByteArrayInputStream(new byte[PhotoZip.LIMIT + 1]));
        byte[] noise = new byte[PhotoZip.LIMIT]; new java.util.Random(42).nextBytes(noise);
        rejects(new ByteArrayInputStream(noise)); // ZIP overhead also counts toward the limit.
        for (String invalid : new String[]{null,"","../photo.jpg","x\\photo.jpg","..",".","x\0y"}) {
            check(PhotoZip.safeName(invalid).equals("photo.jpg"));
        }
        check(PhotoZip.safeName("PXL_20261003.jpg").equals("PXL_20261003.jpg"));
        for (String other : new String[]{"元写真.jpg", "../x", "PXL_MACRO.jpg"}) {
            check(PhotoZip.create(new ByteArrayInputStream(original), other).length == PhotoZip.size(original.length, other));
        }
        Files.write(Paths.get(args[1]), zip);
        System.out.println("PhotoZip: original byte equality, single entry, empty/size/name checks passed");
    }
}
