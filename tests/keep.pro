-keep class R8Smoke {
    public static void main(java.lang.String[]);
}
-keep,allowobfuscation class Crash {
    static void raise();
}
-keepattributes SourceFile,LineNumberTable
