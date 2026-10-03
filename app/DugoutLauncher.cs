// Dugout.exe: FL26 Dugout as its own app window (WebView2, the web engine that ships with Windows), not a
// browser window: its own taskbar button and icon, no address bar.
// Starts Dugout's Python in the background if it is not running yet (.venv\Scripts\pythonw.exe -m dugout
// --no-window, the same as the startup shortcut), waits for it, then shows http://127.0.0.1:8770/.
// One window: starting Dugout.exe again brings it back. Closing the window leaves Dugout running in the
// background (the phone keeps working). Without WebView2 it falls back to an Edge app window as before.
// Build: build_launcher.ps1 (the C# compiler that ships with Windows; WebView2 DLLs in app\webview2).
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using System.Reflection;

// the name Windows shows for the app (taskbar menu, Task Manager): "Dugout", not "Dugout.exe"
[assembly: AssemblyTitle("Dugout")]
[assembly: AssemblyDescription("Dugout")]
[assembly: AssemblyProduct("FL26 Dugout")]
[assembly: AssemblyCompany("FL26 Dugout")]
[assembly: AssemblyVersion("1.1.0.0")]
[assembly: AssemblyFileVersion("1.1.0.0")]

static class DugoutLauncher
{
    public const string Url = "http://127.0.0.1:8770/";

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);

    [STAThread]
    static void Main(string[] args)
    {
        bool created;
        using (var one = new Mutex(true, "FL26.Dugout.Window", out created))
        {
            if (!created) { BringBack(); return; }
            try { SetCurrentProcessExplicitAppUserModelID("FL26.Dugout"); } catch { }
            string dir = AppDomain.CurrentDomain.BaseDirectory;
            if (!ServerUp() && !StartServer(dir)) return;
            Application.EnableVisualStyles();
            Application.Run(new MainForm(dir));
        }
    }

    static void BringBack()
    {
        var me = Process.GetCurrentProcess();
        foreach (var p in Process.GetProcessesByName(me.ProcessName))
        {
            if (p.Id == me.Id || p.MainWindowHandle == IntPtr.Zero) continue;
            if (IsIconic(p.MainWindowHandle)) ShowWindow(p.MainWindowHandle, 9);
            SetForegroundWindow(p.MainWindowHandle);
            return;
        }
    }

    public static bool ServerUp()
    {
        try
        {
            var rq = (HttpWebRequest)WebRequest.Create(Url + "api/status");
            rq.Timeout = 1500;
            rq.Proxy = null;
            using (var rs = (HttpWebResponse)rq.GetResponse()) return rs.StatusCode == HttpStatusCode.OK;
        }
        catch { return false; }
    }

    static bool StartServer(string dir)
    {
        string py = Path.Combine(dir, ".venv", "Scripts", "pythonw.exe");
        if (!File.Exists(py))
        {
            MessageBox.Show("Không tìm thấy Python của Dugout:\n" + py +
                            "\n\nHãy giữ Dugout.exe trong thư mục Dugout (cùng thư mục .venv).",
                            "Dugout", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return false;
        }
        try
        {
            Process.Start(new ProcessStartInfo(py, "-X utf8 -m dugout --no-window")
            {
                WorkingDirectory = dir,
                UseShellExecute = false,
                CreateNoWindow = true
            });
            return true;
        }
        catch (Exception e)
        {
            MessageBox.Show("Không mở được Dugout:\n" + e.Message, "Dugout", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return false;
        }
    }
}

class MainForm : Form
{
    readonly string dir;
    readonly WebView2 web = new WebView2();
    readonly Label wait = new Label();

    public MainForm(string dir)
    {
        this.dir = dir;
        Text = "FL26 Dugout";
        try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
        BackColor = Color.FromArgb(11, 15, 20);
        StartPosition = FormStartPosition.CenterScreen;
        var area = Screen.PrimaryScreen.WorkingArea;
        Size = new Size(Math.Min(1440, area.Width), Math.Min(920, area.Height));
        MinimumSize = new Size(420, 500);
        wait.Text = "Đang mở Dugout…";
        wait.ForeColor = Color.FromArgb(148, 163, 184);
        wait.Font = new Font("Segoe UI", 12f);
        wait.TextAlign = ContentAlignment.MiddleCenter;
        wait.Dock = DockStyle.Fill;
        web.Dock = DockStyle.Fill;
        web.DefaultBackgroundColor = BackColor;
        web.Visible = false;
        Controls.Add(web);
        Controls.Add(wait);
        Load += async (s, e) => await Open();
    }

    async Task Open()
    {
        try
        {
            var env = await CoreWebView2Environment.CreateAsync(null, Path.Combine(dir, "data", "webview2"));
            await web.EnsureCoreWebView2Async(env);
        }
        catch (Exception)
        {
            // no WebView2: the Edge app window, as before
            try { Process.Start("msedge.exe", "--app=" + DugoutLauncher.Url); } catch { Process.Start(DugoutLauncher.Url); }
            Close();
            return;
        }
        var cw = web.CoreWebView2;
        cw.Settings.IsStatusBarEnabled = false;
        cw.NewWindowRequested += (s, e) => { e.Handled = true; try { Process.Start(e.Uri); } catch { } };
        cw.DocumentTitleChanged += (s, e) => { if (!string.IsNullOrEmpty(cw.DocumentTitle)) Text = cw.DocumentTitle; };
        for (int k = 0; k < 120 && !await Task.Run(() => DugoutLauncher.ServerUp()); k++)
        {
            wait.Text = "Đang mở Dugout… (" + (k + 1) + " s)";
            await Task.Delay(1000);
        }
        cw.Navigate(DugoutLauncher.Url);
        wait.Visible = false;
        web.Visible = true;
    }
}
