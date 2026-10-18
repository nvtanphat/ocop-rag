"""Domain layer — pure data models and enums, zero I/O and zero framework.

Nothing here imports ``backend`` or touches Mongo/Neo4j/Qdrant. These types
are the vocabulary the retrieval, graph, agent and generation code speaks;
the infrastructure layer (``backend/``) depends on this, never the reverse.
"""
