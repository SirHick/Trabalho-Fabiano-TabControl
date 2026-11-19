package org.gradle.wrapper;

import java.io.InputStream;
import java.io.IOException;
import java.net.URL;
import java.net.URLConnection;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Properties;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/** Small bootstrap launcher for this sample project: downloads and runs the configured Gradle distribution. */
public final class GradleWrapperMain {
    public static void main(String[] args) throws Exception {
        Path jar = Paths.get(GradleWrapperMain.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        Path projectDir = jar.getParent().getParent().getParent(); // gradle/wrapper/gradle-wrapper.jar -> project root
        Properties properties = new Properties();
        try (InputStream in = Files.newInputStream(projectDir.resolve("gradle/wrapper/gradle-wrapper.properties"))) {
            properties.load(in);
        }
        String distributionUrl = properties.getProperty("distributionUrl");
        if (distributionUrl == null || !distributionUrl.startsWith("https://")) {
            throw new IllegalStateException("distributionUrl HTTPS ausente em gradle-wrapper.properties");
        }
        String zipName = distributionUrl.substring(distributionUrl.lastIndexOf('/') + 1);
        String distributionName = zipName.replaceFirst("-(bin|all)\\.zip$", "");
        Path cache = Paths.get(System.getProperty("user.home"), ".gradle", "wrapper", "dists", "tabcontrol-bootstrap", distributionName);
        Path gradleHome = cache.resolve(distributionName);
        boolean windows = System.getProperty("os.name", "").toLowerCase().contains("win");
        Path gradleExe = gradleHome.resolve("bin").resolve(windows ? "gradle.bat" : "gradle");

        if (!Files.exists(gradleExe)) {
            Files.createDirectories(cache);
            Path zip = cache.resolve(zipName);
            if (!Files.exists(zip)) {
                System.out.println("Baixando a distribuicao oficial do Gradle: " + distributionUrl);
                URLConnection connection = new URL(distributionUrl).openConnection();
                connection.setConnectTimeout(30000);
                connection.setReadTimeout(60000);
                try (InputStream in = connection.getInputStream()) {
                    Files.copy(in, zip, StandardCopyOption.REPLACE_EXISTING);
                }
            }
            unzipSafely(zip, cache);
            if (!Files.exists(gradleExe)) {
                throw new IOException("A distribuicao baixada nao contem o executavel esperado: " + gradleExe);
            }
            if (!windows) gradleExe.toFile().setExecutable(true);
        }

        List<String> command = new ArrayList<>();
        if (windows) {
            command.add("cmd.exe"); command.add("/d"); command.add("/c"); command.add(gradleExe.toString());
        } else {
            command.add(gradleExe.toString());
        }
        for (String arg : args) command.add(arg);
        Process process = new ProcessBuilder(command).directory(projectDir.toFile()).inheritIO().start();
        System.exit(process.waitFor());
    }

    private static void unzipSafely(Path zip, Path destination) throws IOException {
        Path root = destination.toAbsolutePath().normalize();
        try (ZipInputStream in = new ZipInputStream(Files.newInputStream(zip))) {
            ZipEntry entry;
            byte[] buffer = new byte[8192];
            while ((entry = in.getNextEntry()) != null) {
                Path output = root.resolve(entry.getName()).normalize();
                if (!output.startsWith(root)) throw new IOException("Entrada ZIP invalida");
                if (entry.isDirectory()) {
                    Files.createDirectories(output);
                } else {
                    Files.createDirectories(output.getParent());
                    try (var out = Files.newOutputStream(output)) {
                        int count;
                        while ((count = in.read(buffer)) > 0) out.write(buffer, 0, count);
                    }
                }
                in.closeEntry();
            }
        }
    }
}
