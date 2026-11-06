output "function_url" {
  description = "The public URL. The deploy job smoke tests GET /health and POST /summarise on it."
  value       = aws_lambda_function_url.summariser.function_url
}

output "function_name" {
  value = aws_lambda_function.summariser.function_name
}
