set -e

echo "Creating backend repository..."
aws ecr create-repository --repository-name agentic-trading-backend || echo "Backend repo might already exist"

echo "Creating frontend repository..."
aws ecr create-repository --repository-name agentic-trading-frontend || echo "Frontend repo might already exist"

echo "Building backend..."
cd backend
docker buildx build --platform linux/amd64 -t 713220200108.dkr.ecr.us-east-1.amazonaws.com/agentic-trading-backend:latest .
docker push 713220200108.dkr.ecr.us-east-1.amazonaws.com/agentic-trading-backend:latest

echo "Building frontend..."
cd ../frontend
docker buildx build --platform linux/amd64 -t 713220200108.dkr.ecr.us-east-1.amazonaws.com/agentic-trading-frontend:latest .
docker push 713220200108.dkr.ecr.us-east-1.amazonaws.com/agentic-trading-frontend:latest

echo "Deploying to Kubernetes..."
cd ..
kubectl apply -f k8s-deploy.yaml

echo "Committing manifest and deployment files..."
git add k8s-deploy.yaml backend/Dockerfile frontend/Dockerfile deploy.sh
git commit -m "chore: Add Dockerfiles and Kubernetes deployment manifests" || echo "Nothing to commit"
echo "Done!"
