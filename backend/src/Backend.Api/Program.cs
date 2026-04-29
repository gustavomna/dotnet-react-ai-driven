var builder = WebApplication.CreateBuilder(args);

var app = builder.Build();

app.MapGet("/api/health", () => Results.Ok(new HealthResponse("ok")));

app.Run();

public record HealthResponse(string Status);

public partial class Program;
