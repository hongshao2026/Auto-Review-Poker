import java.io.InputStream;
import java.util.jar.JarFile;
import org.brotli.dec.BrotliInputStream;

/** Generic static resource decoder. No HRC classes are loaded. */
public final class BrotliResourceBytes {
    public static void main(String[] args) throws Exception {
        try (JarFile jar = new JarFile(args[0]);
             InputStream raw = jar.getInputStream(jar.getJarEntry(args[1]));
             BrotliInputStream decompressed = new BrotliInputStream(raw)) {
            decompressed.transferTo(System.out);
        }
    }
}
