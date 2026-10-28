-- Budget Buddy synthetic dataset: savings tables only (no Asset / AssetLot / Bond)
-- Matches resource/database.txt. Load into a SEPARATE Supabase project.

DROP TABLE IF EXISTS "GoalEntry" CASCADE;
DROP TABLE IF EXISTS "Goal" CASCADE;
DROP TABLE IF EXISTS "RecurringTransaction" CASCADE;
DROP TABLE IF EXISTS "Transaction" CASCADE;
DROP TABLE IF EXISTS "Category" CASCADE;
DROP TABLE IF EXISTS "Account" CASCADE;
DROP TABLE IF EXISTS "User" CASCADE;

CREATE TABLE "User" (
  "id" SERIAL PRIMARY KEY,
  "email" TEXT NOT NULL,
  "passwordHash" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL
);

CREATE TABLE "Account" (
  "id" SERIAL PRIMARY KEY,
  "name" TEXT NOT NULL,
  "type" TEXT NOT NULL,
  "currency" TEXT NOT NULL,
  "bankName" TEXT,
  "deletedAt" TIMESTAMP(3),
  "userId" INTEGER NOT NULL REFERENCES "User"("id")
);

CREATE TABLE "Category" (
  "id" SERIAL PRIMARY KEY,
  "name" TEXT NOT NULL,
  "color" TEXT,
  "deletedAt" TIMESTAMP(3),
  "type" TEXT NOT NULL,
  "budget" DOUBLE PRECISION,
  "userId" INTEGER NOT NULL REFERENCES "User"("id"),
  "icon" TEXT
);

CREATE TABLE "Transaction" (
  "id" SERIAL PRIMARY KEY,
  "amount" DOUBLE PRECISION NOT NULL,
  "type" TEXT NOT NULL,
  "description" TEXT,
  "date" TIMESTAMP(3) NOT NULL,
  "accountId" INTEGER NOT NULL REFERENCES "Account"("id"),
  "categoryId" INTEGER REFERENCES "Category"("id"),
  "createdAt" TIMESTAMP(3) NOT NULL,
  "deletedAt" TIMESTAMP(3),
  "evidenceUrl" TEXT,
  "userId" INTEGER NOT NULL REFERENCES "User"("id"),
  "source" TEXT
);

CREATE TABLE "RecurringTransaction" (
  "id" SERIAL PRIMARY KEY,
  "amount" DOUBLE PRECISION NOT NULL,
  "type" TEXT NOT NULL,
  "description" TEXT,
  "accountId" INTEGER NOT NULL REFERENCES "Account"("id"),
  "categoryId" INTEGER REFERENCES "Category"("id"),
  "frequency" TEXT NOT NULL,
  "nextDate" TIMESTAMP(3) NOT NULL,
  "active" BOOLEAN NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL,
  "userId" INTEGER NOT NULL REFERENCES "User"("id"),
  "currency" TEXT
);

CREATE TABLE "Goal" (
  "id" SERIAL PRIMARY KEY,
  "userId" INTEGER NOT NULL REFERENCES "User"("id"),
  "name" TEXT NOT NULL,
  "icon" TEXT,
  "target" DOUBLE PRECISION NOT NULL,
  "deadline" TIMESTAMP(3),
  "ruleType" TEXT,
  "ruleValue" DOUBLE PRECISION,
  "createdAt" TIMESTAMP(3) NOT NULL,
  "deletedAt" TIMESTAMP(3)
);

CREATE TABLE "GoalEntry" (
  "id" SERIAL PRIMARY KEY,
  "userId" INTEGER NOT NULL REFERENCES "User"("id"),
  "goalId" INTEGER NOT NULL REFERENCES "Goal"("id"),
  "accountId" INTEGER NOT NULL REFERENCES "Account"("id"),
  "amount" DOUBLE PRECISION NOT NULL,
  "kind" TEXT NOT NULL,
  "transactionId" INTEGER REFERENCES "Transaction"("id"),
  "date" TIMESTAMP(3) NOT NULL,
  "deletedAt" TIMESTAMP(3)
);
