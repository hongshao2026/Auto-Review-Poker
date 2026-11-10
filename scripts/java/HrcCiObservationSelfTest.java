import java.net.*;
import java.nio.file.*;
import java.lang.reflect.*;
public final class HrcCiObservationSelfTest {
  public static void main(String[] args) throws Exception {
    try(URLClassLoader loader=new URLClassLoader(new URL[]{Path.of(args[0]).toUri().toURL()},ClassLoader.getPlatformClassLoader())) {
      Class<?> cls=Class.forName("net.holdemresources.internal.mr",true,loader);
      Constructor<?> constructor=cls.getDeclaredConstructor(int.class,long.class,long.class,double.class);constructor.setAccessible(true);
      Object value=constructor.newInstance(2,123456789L,10000250L,9.125);
      for(Field f:cls.getDeclaredFields()) { f.setAccessible(true);System.out.println(f.getName()+":"+f.getType().getName()+"="+f.get(value)); }
      // A later agentmain invocation may receive a different Instrumentation wrapper.
      // Cleanup must use the owner that registered the transformer, not this argument.
      HrcCiObservationAgent.agentmain("stop",null);
      constructor.newInstance(3,123456790L,10000251L,8.125);
    }
  }
}
