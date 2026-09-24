using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Automation;
using System.Windows.Automation.Text;

internal static class SelectionReader
{
    [StructLayout(LayoutKind.Sequential)]
    private struct Point
    {
        public int X;
        public int Y;
    }

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out Point point);

    [STAThread]
    private static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        try
        {
            IntPtr window = GetForegroundWindow();
            if (args.Length > 0)
            {
                long value;
                if (Int64.TryParse(args[0], out value)) window = new IntPtr(value);
            }

            Point point;
            if (GetCursorPos(out point) &&
                (window == IntPtr.Zero || AutomationElement.FromHandle(window).Current.BoundingRectangle.Contains(point.X, point.Y)))
            {
                AutomationElement element = AutomationElement.FromPoint(
                    new System.Windows.Point(point.X, point.Y));
                for (int depth = 0; element != null && depth < 8; depth++)
                {
                    string selected = ReadSelection(element);
                    if (!String.IsNullOrWhiteSpace(selected))
                    {
                        Console.Write(selected);
                        return 0;
                    }

                    try
                    {
                        element = TreeWalker.ControlViewWalker.GetParent(element);
                    }
                    catch
                    {
                        element = null;
                    }
                }
            }

            AutomationElement focused = AutomationElement.FocusedElement;
            for (int depth = 0; focused != null && depth < 8; depth++)
            {
                string selected = ReadSelection(focused);
                if (!String.IsNullOrWhiteSpace(selected))
                {
                    Console.Write(selected);
                    return 0;
                }
                try
                {
                    focused = TreeWalker.ControlViewWalker.GetParent(focused);
                }
                catch
                {
                    focused = null;
                }
            }
        }
        catch
        {
            return 2;
        }
        return 1;
    }

    private static string ReadSelection(AutomationElement element)
    {
        try
        {
            object patternObject;
            if (!element.TryGetCurrentPattern(TextPattern.Pattern, out patternObject)) return String.Empty;
            TextPattern pattern = (TextPattern)patternObject;
            TextPatternRange[] ranges = pattern.GetSelection();
            StringBuilder text = new StringBuilder();
            foreach (TextPatternRange range in ranges)
            {
                string value = range.GetText(-1);
                if (!String.IsNullOrWhiteSpace(value))
                {
                    if (text.Length > 0) text.AppendLine();
                    text.Append(value.Trim());
                }
            }
            return text.ToString();
        }
        catch
        {
            return String.Empty;
        }
    }
}
