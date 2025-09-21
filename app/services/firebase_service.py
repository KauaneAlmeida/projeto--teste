"""
Firebase Service (com Secret Manager)

Este módulo gerencia a integração com o Firebase Admin SDK e operações no Firestore.
Agora o backend usa **exclusivamente** a variável de ambiente FIREBASE_KEY,
que deve conter o JSON completo da service account (via Secret Manager no Cloud Run).
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from fastapi import HTTPException, status

# Configure logging
logger = logging.getLogger(__name__)

# Global Firebase app instance
_firebase_app = None
_firestore_client = None


def initialize_firebase():
    """
    Initialize Firebase Admin SDK from FIREBASE_KEY environment variable.
    """
    global _firebase_app, _firestore_client

    if _firebase_app is not None:
        logger.info("✅ Firebase already initialized")
        return

    try:
        firebase_key = os.getenv("FIREBASE_KEY")
        if not firebase_key:
            raise ValueError("FIREBASE_KEY environment variable not found.")

        # Convert JSON from env to dict
        firebase_credentials = json.loads(firebase_key)
        cred = credentials.Certificate(firebase_credentials)

        logger.info("🔥 Initializing Firebase with credentials from environment")
        _firebase_app = firebase_admin.initialize_app(cred)
        _firestore_client = firestore.client()
        logger.info("✅ Firebase initialized successfully")

    except Exception as e:
        logger.error(f"❌ Failed to initialize Firebase: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Firebase initialization failed: {str(e)}",
        )


def get_firestore_client():
    """
    Return Firestore client instance.
    """
    if _firestore_client is None:
        initialize_firebase()

    if _firestore_client is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Firestore client not available",
        )

    return _firestore_client


# --------------------------------------------------------------------------
# Conversation Flow
# --------------------------------------------------------------------------
async def get_conversation_flow() -> Dict[str, Any]:
    try:
        db = get_firestore_client()
        flow_ref = db.collection("conversation_flows").document("law_firm_intake")
        flow_doc = flow_ref.get()

        if not flow_doc.exists:
            logger.info("📝 Criando fluxo de conversa padrão")
            default_flow = {
                "steps": [
                    {"id": 0, "question": "Olá! Para garantir que registramos corretamente suas informações, vamos começar do início. Tudo bem?"},
                    {"id": 1, "question": "Qual é o seu nome completo?"},
                    {"id": 2, "question": "Em qual área do direito você precisa de ajuda?\n\n• Penal\n• Saúde Liminar"},
                    {"id": 3, "question": "Por favor, descreva brevemente sua situação ou problema jurídico."},
                    {"id": 4, "question": "Gostaria de agendar uma consulta com nosso advogado especializado? (Sim ou Não)"},
                ],
                "completion_message": "Perfeito! Suas informações foram registradas com sucesso. Nossa equipe especializada analisará seu caso e entrará em contato em breve. Obrigado por escolher nossos serviços jurídicos!",
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "version": "1.0",
                "description": "Fluxo de captação de leads para escritório de advocacia",
            }

            flow_ref.set(default_flow)
            logger.info("✅ Fluxo de conversa padrão criado")
            return default_flow

        flow_data = flow_doc.to_dict()
        steps = flow_data.get("steps", [])

        # Normaliza steps
        normalized_steps = []
        for idx, step in enumerate(steps, start=1):
            if isinstance(step, dict):
                normalized_steps.append({
                    "id": step.get("id", idx),
                    "question": step.get("question", ""),
                })
            else:
                normalized_steps.append({
                    "id": idx,
                    "question": str(step),
                })

        if not any(step.get("id") == 0 for step in normalized_steps):
            normalized_steps.insert(0, {
                "id": 0,
                "question": "Olá! Para garantir que registramos corretamente suas informações, vamos começar do início. Tudo bem?"
            })

        flow_data["steps"] = normalized_steps

        if "completion_message" not in flow_data:
            flow_data["completion_message"] = "Obrigado! Suas informações foram registradas e entraremos em contato em breve."

        return flow_data

    except Exception as e:
        logger.error(f"❌ Erro ao buscar fluxo de conversa: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Falha ao recuperar fluxo de conversa",
        )


# --------------------------------------------------------------------------
# Fallback Questions
# --------------------------------------------------------------------------
async def get_fallback_questions() -> list[str]:
    try:
        flow = await get_conversation_flow()
        steps = flow.get("steps", [])
        return [step["question"] for step in steps if "question" in step]
    except Exception as e:
        logger.error(f"❌ Erro ao buscar perguntas de fallback: {e}")
        return []


# --------------------------------------------------------------------------
# Lead Management
# --------------------------------------------------------------------------
async def save_lead_data(lead_data: Dict[str, Any]) -> str:
    try:
        db = get_firestore_client()

        lead_doc = {
            "answers": lead_data.get("answers", []),
            "timestamp": datetime.now(),
            "status": "new",
            "source": "chatbot_intake",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }

        leads_ref = db.collection("leads")
        doc_ref = leads_ref.add(lead_doc)
        lead_id = doc_ref[1].id
        logger.info(f"💾 Lead saved with ID: {lead_id}")
        return lead_id

    except Exception as e:
        logger.error(f"❌ Erro ao salvar lead: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Falha ao salvar lead",
        )


async def update_lead_data(lead_id: str, update_data: Dict[str, Any]) -> bool:
    try:
        db = get_firestore_client()
        update_data["updated_at"] = datetime.now()
        db.collection("leads").document(lead_id).update(update_data)
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao atualizar lead: {str(e)}")
        return False


# --------------------------------------------------------------------------
# Session Management
# --------------------------------------------------------------------------
async def get_user_session(session_id: str) -> Optional[Dict[str, Any]]:
    try:
        db = get_firestore_client()
        doc = db.collection("user_sessions").document(session_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        logger.error(f"❌ Erro ao buscar sessão {session_id}: {str(e)}")
        return None


async def save_user_session(session_id: str, session_data: Dict[str, Any]) -> bool:
    try:
        db = get_firestore_client()
        session_data["last_updated"] = datetime.now()
        if "created_at" not in session_data:
            session_data["created_at"] = datetime.now()
        db.collection("user_sessions").document(session_id).set(session_data, merge=True)
        return True
    except Exception as e:
        logger.error(f"❌ Erro ao salvar sessão {session_id}: {str(e)}")
        return False


# --------------------------------------------------------------------------
# Health Check
# --------------------------------------------------------------------------
async def get_firebase_service_status() -> Dict[str, Any]:
    try:
        db = get_firestore_client()
        try:
            test_collection = db.collection("conversation_flows").limit(1)
            _ = test_collection.get()
            logger.info("✅ Firebase Firestore connection test successful")
        except Exception as read_error:
            logger.error(f"❌ Firebase Firestore connection test failed: {str(read_error)}")
            raise read_error

        return {
            "service": "firebase_service",
            "status": "active",
            "firestore_connected": True,
            "credentials_source": "env:FIREBASE_KEY",
            "collections": ["conversation_flows", "leads", "user_sessions", "_health_check"],
            "message": "Firebase Firestore is operational",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Firebase health check failed: {str(e)}")
        return {
            "service": "firebase_service",
            "status": "error",
            "firestore_connected": False,
            "error": str(e),
            "configuration_required": True,
            "message": f"Firebase connection failed: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }


# Inicializa no import
try:
    initialize_firebase()
    logger.info("🔥 Módulo Firebase service carregado com sucesso")
except Exception as e:
    logger.warning(f"⚠️ Inicialização adiada do Firebase: {str(e)}")
